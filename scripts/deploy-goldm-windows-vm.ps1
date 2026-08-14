param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TaskName = "goldm telegram worker",
    [string]$PythonExecutable = "py",
    [string]$TerminalDataPath = "",
    [string]$MetaEditorPath = "C:\Program Files\MetaTrader 5\MetaEditor64.exe",
    [switch]$SkipGitPull,
    [switch]$SkipVerification,
    [switch]$RestartTerminal,
    [switch]$TelegramSmokeTest
)

$ErrorActionPreference = "Stop"

function Resolve-TerminalDataPath {
    param([string]$ExplicitPath)
    if ($ExplicitPath) {
        return (Resolve-Path -LiteralPath $ExplicitPath).Path
    }
    $probe = & $PythonExecutable -c "import MetaTrader5 as m; assert m.initialize(), m.last_error(); print(m.terminal_info().data_path); m.shutdown()"
    if ($LASTEXITCODE -ne 0 -or -not $probe) {
        throw "Cannot discover MT5 terminal data path"
    }
    return $probe.Trim()
}

Set-Location -LiteralPath $RepoRoot
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
if (-not $SkipGitPull) {
    & git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "git pull failed" }
}
& $PythonExecutable -m pip install -e ".[live]"
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

if (-not $SkipVerification) {
    & (Join-Path $RepoRoot "scripts\verify-goldm-release.ps1") `
        -RepoRoot $RepoRoot `
        -PythonExecutable $PythonExecutable `
        -MetaEditorPath $MetaEditorPath
    if ($LASTEXITCODE -ne 0) { throw "release verification failed" }
}

$dataPath = Resolve-TerminalDataPath -ExplicitPath $TerminalDataPath
$expertDir = Join-Path $dataPath "MQL5\Experts\bot-ea"
$sourceEa = Join-Path $RepoRoot "mt5\Experts\bot-ea\GoldMSniperParity.mq5"
$targetEa = Join-Path $expertDir "GoldMSniperParity.mq5"
$targetEx5 = [System.IO.Path]::ChangeExtension($targetEa, ".ex5")
$backupRoot = Join-Path $RepoRoot ("runtime_data\deploy-backups\" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Force -Path $expertDir, $backupRoot | Out-Null

foreach ($path in @(
    (Join-Path $RepoRoot ".env"),
    (Join-Path $RepoRoot "runtime_data\goldm_signal.db"),
    $targetEa,
    $targetEx5
)) {
    if (Test-Path -LiteralPath $path) {
        Copy-Item -LiteralPath $path -Destination $backupRoot -Force
    }
}

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
try {
    Copy-Item -LiteralPath $sourceEa -Destination $targetEa -Force
    $compileLog = Join-Path $backupRoot "GoldMSniperParity.compile.log"
    Start-Process -FilePath $MetaEditorPath -ArgumentList @(
        "/compile:$targetEa",
        "/log:$compileLog"
    ) -Wait -PassThru -WindowStyle Hidden | Out-Null
    $result = Get-Content -LiteralPath $compileLog -Raw
    if (-not (Test-Path -LiteralPath $targetEx5) -or $result -notmatch "Result:\s+0 errors,\s+0 warnings") {
        throw "Active EA compile failed. Log: $compileLog"
    }

    if ($RestartTerminal) {
        $terminal = Get-Process terminal64 -ErrorAction SilentlyContinue
        if ($terminal) {
            $terminal | Stop-Process -Force
            Start-Sleep -Seconds 2
        }
        $terminalPath = Join-Path (Split-Path -Parent $MetaEditorPath) "terminal64.exe"
        Start-Process -FilePath $terminalPath -WindowStyle Hidden
        Start-Sleep -Seconds 8
    }

    if ($TelegramSmokeTest) {
        & $PythonExecutable -m goldm_signal.notify.cli --debug-notification --once
        if ($LASTEXITCODE -ne 0) { throw "Telegram smoke test failed" }
    }
}
catch {
    $backupEa = Join-Path $backupRoot "GoldMSniperParity.mq5"
    $backupEx5 = Join-Path $backupRoot "GoldMSniperParity.ex5"
    if (Test-Path -LiteralPath $backupEa) { Copy-Item -LiteralPath $backupEa -Destination $targetEa -Force }
    if (Test-Path -LiteralPath $backupEx5) { Copy-Item -LiteralPath $backupEx5 -Destination $targetEx5 -Force }
    throw
}
finally {
    Start-ScheduledTask -TaskName $TaskName
}

Start-Sleep -Seconds 3
$state = (Get-ScheduledTask -TaskName $TaskName).State
if ($state -ne "Running") { throw "Worker task is not running: $state" }
Write-Output "DEPLOY_OK"
Write-Output "commit=$(& git rev-parse --short HEAD)"
Write-Output "worker_state=$state"
Write-Output "terminal_data_path=$dataPath"
Write-Output "backup=$backupRoot"
Write-Output "ea_attach_note=On a new host, attach GoldMSniperParity once to the GOLD.i# M15 chart and save the MT5 profile."
