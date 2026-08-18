param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TaskName = "goldm telegram worker",
    [string]$Remote = "origin",
    [string]$RemoteBranch = "feature/goldm-watch-entry-distance-defer"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-ElevatedCopy {
    $argumentLine = @(
        "-NoLogo"
        "-NoProfile"
        "-ExecutionPolicy Bypass"
        "-File `"$PSCommandPath`""
        "-RepoRoot `"$RepoRoot`""
        "-TaskName `"$TaskName`""
        "-Remote `"$Remote`""
        "-RemoteBranch `"$RemoteBranch`""
    ) -join " "
    $process = Start-Process `
        -FilePath "powershell.exe" `
        -Verb RunAs `
        -ArgumentList $argumentLine `
        -Wait `
        -PassThru
    exit $process.ExitCode
}

function Get-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $pattern = '^\s*' + [regex]::Escape($Name) + '\s*=\s*(.*)\s*$'
    foreach ($line in Get-Content -LiteralPath $Path -ErrorAction Stop) {
        $match = [regex]::Match($line, $pattern)
        if (-not $match.Success) { continue }
        $value = $match.Groups[1].Value.Trim()
        if ($value.Length -ge 2 -and (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        )) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        return $value
    }
    throw "Missing $Name in private runtime environment"
}

function Resolve-BasePythonExecutable {
    param([Parameter(Mandatory = $true)][string]$ReleaseRoot)
    $configuration = Join-Path $ReleaseRoot ".venv\pyvenv.cfg"
    $homeLine = Get-Content -LiteralPath $configuration -ErrorAction Stop |
        Where-Object { $_ -match '^\s*home\s*=\s*(.+?)\s*$' } |
        Select-Object -First 1
    if (-not $homeLine) { throw "Active release pyvenv.cfg has no base Python home" }
    $home = ([regex]::Match($homeLine, '^\s*home\s*=\s*(.+?)\s*$')).Groups[1].Value
    $python = Join-Path $home "python.exe"
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Base Python executable is missing: $python"
    }
    return [System.IO.Path]::GetFullPath($python)
}

if (-not (Test-IsAdministrator)) {
    Invoke-ElevatedCopy
}

Import-Module (Join-Path $PSScriptRoot "goldm-deployment-common.psm1") -Force

try {
    $RepoRoot = Resolve-GoldMDirectory -Path $RepoRoot -Label "repository root"
    if ($Remote -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
        throw "Remote contains unsupported characters"
    }
    if (
        $RemoteBranch -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]*$' -or
        $RemoteBranch.Contains('..') -or
        $RemoteBranch.Contains('//') -or
        $RemoteBranch.Contains('@{')
    ) {
        throw "Remote branch contains unsupported characters"
    }

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $actions = @($task.Actions)
    if ($actions.Count -ne 1) {
        throw "Scheduled Task must have exactly one action: $TaskName"
    }
    $activeAppRoot = Resolve-GoldMDirectory `
        -Path ([string]$actions[0].WorkingDirectory) `
        -Label "active worker application root"
    if ((Split-Path -Leaf $activeAppRoot) -cne "app") {
        throw "Active worker application root must be a sealed release app directory"
    }
    $activeReleaseRoot = Resolve-GoldMDirectory `
        -Path (Split-Path -Parent $activeAppRoot) `
        -Label "active release root"
    $metadataPath = Resolve-GoldMFile `
        -Path (Join-Path $activeReleaseRoot "source-metadata.json") `
        -Label "active release source metadata"
    $metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json

    $pythonExecutable = Resolve-BasePythonExecutable -ReleaseRoot $activeReleaseRoot
    $pythonSha256 = [string]$metadata.basePython.sha256
    if ($pythonSha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Active release base Python SHA-256 is invalid"
    }

    $sealedInputsRoot = Resolve-GoldMDirectory `
        -Path (Join-Path $activeReleaseRoot "sealed-inputs") `
        -Label "active release sealed inputs"
    $wheelhouses = @(Get-ChildItem -LiteralPath $sealedInputsRoot -Directory -Force)
    if ($wheelhouses.Count -ne 1) {
        throw "Active release must contain exactly one sealed wheelhouse"
    }
    $wheelhousePath = $wheelhouses[0].FullName
    $wheelhouseManifestSha256 = [string]$metadata.wheelhouse.manifestSha256
    if ($wheelhouseManifestSha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Active release wheelhouse manifest SHA-256 is invalid"
    }

    $envFile = Resolve-GoldMFile `
        -Path (Join-Path $RepoRoot "runtime_data\config\runtime.env") `
        -Label "private runtime environment"
    $databasePath = Resolve-GoldMFile `
        -Path (Join-Path $RepoRoot "runtime_data\goldm_signal.db") `
        -Label "GOLDM database"
    $terminalExecutable = Resolve-GoldMFile `
        -Path (Get-DotEnvValue -Path $envFile -Name "MT5_PATH") `
        -Label "MT5 executable"
    $terminalDataPath = Resolve-GoldMDirectory `
        -Path (Get-DotEnvValue -Path $envFile -Name "MT5_DATA_PATH") `
        -Label "MT5 data path"
    $metaEditorPath = Resolve-GoldMFile `
        -Path (Join-Path (Split-Path -Parent $terminalExecutable) "metaeditor64.exe") `
        -Label "MetaEditor executable"

    Set-Location -LiteralPath $RepoRoot
    Invoke-GoldMNativeChecked "git_fetch_operator_update" {
        & git fetch --no-tags --prune $Remote $RemoteBranch
    }
    $expectedCommit = (& git rev-parse "FETCH_HEAD^{commit}").Trim()
    if ($LASTEXITCODE -ne 0 -or $expectedCommit -notmatch '^[0-9a-f]{40}$') {
        throw "Remote update did not resolve to an immutable commit"
    }

    Write-Host ""
    Write-Host "GOLDM BOT UPDATE" -ForegroundColor Cyan
    Write-Host "Remote : $Remote/$RemoteBranch"
    Write-Host "Commit : $expectedCommit"
    Write-Host ""
    $confirmation = Read-Host "Type UPDATE to run backup, verification, deploy, restart, and rollback protection"
    if ($confirmation -cne "UPDATE") {
        Write-Host "Update cancelled; no deployment change was made." -ForegroundColor Yellow
        exit 2
    }

    & (Join-Path $PSScriptRoot "update-goldm-windows-vm.ps1") `
        -RepoRoot $RepoRoot `
        -TaskName $TaskName `
        -PythonExecutable $pythonExecutable `
        -PythonSha256 $pythonSha256 `
        -TerminalExecutable $terminalExecutable `
        -TerminalDataPath $terminalDataPath `
        -MetaEditorPath $metaEditorPath `
        -WheelhousePath $wheelhousePath `
        -WheelhouseManifestSha256 $wheelhouseManifestSha256 `
        -Remote $Remote `
        -RemoteBranch $RemoteBranch `
        -ExpectedCommit $expectedCommit `
        -EnvFile $envFile `
        -DatabasePath $databasePath
    if (-not $?) { throw "GOLDM update pipeline failed" }
    Write-Host "GOLDM bot update completed successfully." -ForegroundColor Green
    exit 0
}
catch {
    Write-Host ""
    Write-Host "GOLDM bot update failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

