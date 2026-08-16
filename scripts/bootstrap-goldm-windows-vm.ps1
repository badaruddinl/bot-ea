param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TaskName = "goldm telegram worker",
    [Parameter(Mandatory = $true)][string]$PythonExecutable,
    [Parameter(Mandatory = $true)][string]$PythonSha256,
    [Parameter(Mandatory = $true)][string]$TerminalExecutable,
    [Parameter(Mandatory = $true)][string]$TerminalDataPath,
    [Parameter(Mandatory = $true)][string]$MetaEditorPath,
    [Parameter(Mandatory = $true)][string]$WheelhousePath,
    [Parameter(Mandatory = $true)][string]$WheelhouseManifestSha256,
    [string]$EnvFile = "",
    [string]$DatabasePath = "",
    [string]$ReleaseCommit = "HEAD",
    [string]$MaintenanceRecoveryJournalSha256 = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot "goldm-deployment-common.psm1") -Force

function Invoke-BootstrapReleaseHelper {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    return Invoke-GoldMDeploymentHelper `
        -PythonExecutable $script:ReleasePython `
        -RepoRoot $script:ApplicationRoot `
        -Arguments $Arguments
}

$RepoRoot = Resolve-GoldMDirectory -Path $RepoRoot -Label "repository root"
$maintenanceLock = Enter-GoldMMaintenanceLock `
    -Operation "bootstrap" `
    -RecoveryJournalSha256 $MaintenanceRecoveryJournalSha256
$maintenancePrimaryError = $null
try {
foreach ($binding in @(
    @($PythonExecutable, "PythonExecutable"),
    @($TerminalExecutable, "TerminalExecutable"),
    @($TerminalDataPath, "TerminalDataPath"),
    @($MetaEditorPath, "MetaEditorPath"),
    @($WheelhousePath, "WheelhousePath")
)) {
    Assert-GoldMAbsolutePathInput -Path ([string]$binding[0]) -Label ([string]$binding[1])
}
$TerminalExecutable = Resolve-GoldMFile -Path $TerminalExecutable -Label "terminal executable"
$TerminalDataPath = Resolve-GoldMDirectory -Path $TerminalDataPath -Label "terminal data path"
$MetaEditorPath = Assert-GoldMMetaEditorExecutable -MetaEditorPath $MetaEditorPath
$WheelhousePath = Resolve-GoldMDirectory -Path $WheelhousePath -Label "sealed offline wheelhouse"
if ($WheelhouseManifestSha256 -notmatch "^[0-9a-fA-F]{64}$") {
    throw "WheelhouseManifestSha256 must contain exactly 64 hexadecimal characters"
}
[void](Assert-GoldMReadOnlyFlatDirectory -Path $WheelhousePath)
$pythonContract = Assert-GoldMPythonInterpreter `
    -PythonExecutable $PythonExecutable `
    -ExpectedSha256 $PythonSha256
$PythonExecutable = [string]$pythonContract.Path
[void](Invoke-GoldMDeploymentHelper `
    -PythonExecutable $PythonExecutable `
    -RepoRoot $RepoRoot `
    -Arguments @(
        "verify-offline-wheelhouse", "--root", $WheelhousePath,
        "--expected-manifest-sha256", $WheelhouseManifestSha256
    ))
[void](Assert-GoldMStandardTerminalTopology `
    -TerminalExecutable $TerminalExecutable `
    -TerminalDataPath $TerminalDataPath)

$terminalInstall = Split-Path -Parent $TerminalExecutable
$editorInstall = Split-Path -Parent $MetaEditorPath
if (-not [string]::Equals($terminalInstall, $editorInstall, [StringComparison]::OrdinalIgnoreCase)) {
    throw "TerminalExecutable and MetaEditorPath must belong to the same exact MT5 installation"
}

$EnvFile = if ($EnvFile) {
    if (-not [System.IO.Path]::IsPathRooted($EnvFile)) {
        throw "EnvFile must be an absolute path"
    }
    [System.IO.Path]::GetFullPath($EnvFile)
}
else {
    Join-Path $RepoRoot ".env"
}
$DatabasePath = if ($DatabasePath) {
    if (-not [System.IO.Path]::IsPathRooted($DatabasePath)) {
        throw "DatabasePath must be an absolute path"
    }
    [System.IO.Path]::GetFullPath($DatabasePath)
}
else {
    Join-Path $RepoRoot "runtime_data\goldm_signal.db"
}

foreach ($requiredDirectory in @(
    (Join-Path $TerminalDataPath "MQL5"),
    (Join-Path $TerminalDataPath "MQL5\Logs")
)) {
    if (-not (Test-Path -LiteralPath $requiredDirectory -PathType Container)) {
        throw "Explicit terminal data path is not initialized by MT5: $requiredDirectory"
    }
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Required command not found: git"
}

if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
    Copy-Item -LiteralPath (Join-Path $RepoRoot ".env.example") -Destination $EnvFile
    throw ".env was created from .env.example. Fill all exact demo bindings and secrets, keep execution OFF, then rerun bootstrap."
}
$sourceEnvEvidence = Get-GoldMFileEvidence -Path $EnvFile

$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
    throw "Scheduled Task already exists; bootstrap never replaces it. Use deploy/update or perform an explicit reviewed manual recovery."
}
if ($ReleaseCommit -ne "HEAD" -and $ReleaseCommit -notmatch "^[0-9a-f]{40}$") {
    throw "ReleaseCommit must be HEAD or one full lowercase 40-hex commit SHA"
}

Set-Location -LiteralPath $RepoRoot
Invoke-GoldMNativeChecked "bootstrap_release_commit_resolve" {
    & git cat-file -e ($ReleaseCommit + "^{commit}")
}
$fullCommit = (& git rev-parse ($ReleaseCommit + "^{commit}")).Trim()
if ($LASTEXITCODE -ne 0 -or $fullCommit -notmatch "^[0-9a-f]{40}$") {
    throw "ReleaseCommit did not resolve to an immutable Git commit"
}

$runtimeRoot = Join-Path $RepoRoot "runtime_data"
[void](Assert-GoldMPathWithinDirectory `
    -Path $DatabasePath `
    -Directory $runtimeRoot `
    -Label "DatabasePath")
[void](New-GoldMPrivateDirectory -Path $runtimeRoot)
$runtimeConfigRoot = Join-Path $runtimeRoot "config"
[void](New-GoldMPrivateDirectory -Path $runtimeConfigRoot)
$runtimeEnvFile = Join-Path $runtimeConfigRoot "runtime.env"
$releasesRoot = Join-Path $runtimeRoot "releases"
[void](New-GoldMPrivateDirectory -Path $releasesRoot)
$releaseId = "bootstrap-" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ") + "-" + $fullCommit.Substring(0, 12) + "-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
$releaseRoot = Join-Path $releasesRoot $releaseId
[void](New-GoldMPrivateDirectory -Path $releaseRoot)
$envStagingRoot = Join-Path $runtimeRoot "env-staging"
[void](New-GoldMPrivateDirectory -Path $envStagingRoot)
$privateEnvStageDirectory = Join-Path $envStagingRoot $releaseId
$privateEnvStageEvidence = Copy-GoldMFileToPrivateStage `
    -Source $EnvFile `
    -StageDirectory $privateEnvStageDirectory `
    -ExpectedSha256 ([string]$sourceEnvEvidence.Sha256)
$stagedSourceEnvFile = [string]$privateEnvStageEvidence.Path
$script:ApplicationRoot = Join-Path $releaseRoot "app"
$sourceArchive = Join-Path $releaseRoot "source.zip"
New-Item -ItemType Directory -Path $ApplicationRoot | Out-Null

Invoke-GoldMNativeChecked "bootstrap_git_archive" {
    & git archive --format=zip --output=$sourceArchive $fullCommit
}
Expand-Archive -LiteralPath $sourceArchive -DestinationPath $ApplicationRoot
$sealedInputsRoot = Join-Path $releaseRoot "sealed-inputs"
[void](New-GoldMPrivateDirectory -Path $sealedInputsRoot)
$wheelhouseLeaf = Split-Path -Leaf $WheelhousePath
if ($wheelhouseLeaf -notmatch '^[A-Za-z0-9._-]+$') {
    throw "External wheelhouse leaf name is not portable for private staging"
}
$stagedWheelhouse = Join-Path $sealedInputsRoot $wheelhouseLeaf
$wheelhouseStage = Copy-GoldMVerifiedWheelhouseToPrivateStage `
    -SourcePath $WheelhousePath `
    -DestinationPath $stagedWheelhouse `
    -ExpectedManifestSha256 $WheelhouseManifestSha256 `
    -PythonExecutable $PythonExecutable `
    -RepoRoot $ApplicationRoot
$wheelhouseContract = [pscustomobject]@{
    manifest_sha256 = [string]$wheelhouseStage.ManifestSha256
    lock_sha256 = [string]$wheelhouseStage.LockSha256
}
$wheelhouseLock = Join-Path $stagedWheelhouse "requirements-goldm-live.lock"

$venvRoot = Join-Path $releaseRoot ".venv"
$script:ReleasePython = Join-Path $venvRoot "Scripts\python.exe"
$releasePythonw = Join-Path $venvRoot "Scripts\pythonw.exe"
Invoke-GoldMNativeChecked "bootstrap_release_venv_create" {
    & $PythonExecutable -I -B -m venv $venvRoot
}
foreach ($path in @($ReleasePython, $releasePythonw)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "sealed bootstrap release virtual environment is incomplete: $path"
    }
}
[void](Assert-GoldMPythonRuntime -PythonExecutable $ReleasePython)
[void](Install-GoldMOfflinePythonRelease `
    -PythonExecutable $ReleasePython `
    -ApplicationRoot $ApplicationRoot `
    -WheelhousePath $stagedWheelhouse `
    -RequirementsLock $wheelhouseLock)
[void](Invoke-BootstrapReleaseHelper -Arguments @(
    "verify-offline-wheelhouse", "--root", $stagedWheelhouse,
    "--expected-manifest-sha256", $WheelhouseManifestSha256
))
[void](Invoke-BootstrapReleaseHelper -Arguments @(
    "validate-env",
    "--env-file", $stagedSourceEnvFile,
    "--terminal-executable", $TerminalExecutable,
    "--terminal-data-path", $TerminalDataPath
))
[void](Assert-GoldMFileMatchesEvidence `
    -Path $stagedSourceEnvFile `
    -Evidence $privateEnvStageEvidence `
    -Label "validated private staged environment")
Install-GoldMFileAtomically `
    -Source $stagedSourceEnvFile `
    -Destination $runtimeEnvFile `
    -ExpectedSha256 ([string]$privateEnvStageEvidence.Sha256)
Remove-Item -LiteralPath $stagedSourceEnvFile -Force
Remove-Item -LiteralPath $privateEnvStageDirectory -Force
if (Test-Path -LiteralPath $privateEnvStageDirectory) {
    throw "private environment staging leaf was not removed after bootstrap"
}
[void](Protect-GoldMPrivateFile -Path $runtimeEnvFile)
[void](Invoke-BootstrapReleaseHelper -Arguments @(
    "validate-env",
    "--env-file", $runtimeEnvFile,
    "--terminal-executable", $TerminalExecutable,
    "--terminal-data-path", $TerminalDataPath
))
$runtimeConfigSha256 = Get-GoldMFileSha256 -Path $runtimeEnvFile
if (-not [string]::Equals(
    $runtimeConfigSha256,
    [string]$privateEnvStageEvidence.Sha256,
    [StringComparison]::Ordinal
)) {
    throw "authoritative runtime environment differs from the private staged input"
}
$productionContract = Invoke-BootstrapReleaseHelper -Arguments @(
    "production-input-contract"
)

& (Join-Path $ApplicationRoot "scripts\verify-goldm-release.ps1") `
    -RepoRoot $ApplicationRoot `
    -PythonExecutable $ReleasePython `
    -MetaEditorPath $MetaEditorPath `
    -SkipGitDiffCheck
if ($LASTEXITCODE -ne 0) {
    throw "sealed bootstrap release verification failed"
}

Invoke-GoldMNativeChecked "bootstrap_release_pip_freeze" {
    & $ReleasePython -I -B -m pip --isolated freeze --all |
        Set-Content -LiteralPath (Join-Path $releaseRoot "python-packages.txt") -Encoding UTF8
}
$releaseMetadata = [ordered]@{
    schemaVersion = 2
    purpose = "GOLDM_BOOTSTRAP_RELEASE"
    releaseId = $releaseId
    commit = $fullCommit
    sourceArchiveSha256 = Get-GoldMFileSha256 -Path $sourceArchive
    runtimeConfigSha256 = $runtimeConfigSha256
    productionConfigSha256 = [string]$productionContract.sha256
    basePython = [ordered]@{
        sha256 = [string]$pythonContract.Sha256
        version = [string]$pythonContract.Version
        architecture = [string]$pythonContract.Architecture
    }
    wheelhouse = [ordered]@{
        manifestSha256 = [string]$wheelhouseContract.manifest_sha256
        requirementsLockSha256 = [string]$wheelhouseContract.lock_sha256
    }
    preparedAtUtc = [DateTime]::UtcNow.ToString("o")
}
Write-GoldMUtf8NoBomFile `
    -Value ($releaseMetadata | ConvertTo-Json -Depth 8) `
    -Path (Join-Path $releaseRoot "source-metadata.json")
$treeManifestPath = Join-Path $releaseRoot "release-tree-manifest.json"
$treeManifest = Invoke-BootstrapReleaseHelper -Arguments @(
    "build-tree-manifest", "--root", $releaseRoot, "--output", $treeManifestPath
)
[void](Invoke-BootstrapReleaseHelper -Arguments @(
    "verify-tree-manifest", "--root", $releaseRoot, "--manifest", $treeManifestPath,
    "--expected-manifest-sha256", [string]$treeManifest.sha256
))

# Schema creation is deliberately delayed until the exact target commit has
# been exported, dependency-sealed, verified, and tree-manifested. Existing
# databases are verified read-only; bootstrap never performs an implicit
# migration of an operational database.
$databaseDirectory = Split-Path -Parent $DatabasePath
[void](New-GoldMPrivateDirectory -Path $databaseDirectory)
if (Test-Path -LiteralPath $DatabasePath -PathType Leaf) {
    [void](Protect-GoldMDatabaseArtifacts -DatabasePath $DatabasePath)
}
else {
    $databaseSourceRoot = Resolve-GoldMDirectory `
        -Path (Join-Path $ApplicationRoot "src") `
        -Label "sealed bootstrap database source"
    $databaseSitePackages = Resolve-GoldMPythonSitePackagesDirectory `
        -PythonExecutable $ReleasePython
    $databaseBootstrap = "import sys; sys.path[:0]=[sys.argv.pop(1),sys.argv.pop(1)]; from goldm_signal.storage import SignalStore; SignalStore(sys.argv[1]).initialize()"
    Invoke-GoldMNativeChecked "database_initialize_from_sealed_release" {
        & $ReleasePython -I -S -B -c $databaseBootstrap `
            $databaseSourceRoot $databaseSitePackages $DatabasePath
    }
    [void](Protect-GoldMDatabaseArtifacts -DatabasePath $DatabasePath)
}
[void](Invoke-BootstrapReleaseHelper -Arguments @(
    "inspect-db", "--database", $DatabasePath, "--require-quiescent"
))

$deploymentNonce = New-GoldMDeploymentNonce
$workerArguments = New-GoldMWorkerArgumentLine `
    -ReleaseRoot $releaseRoot `
    -ApplicationRoot $ApplicationRoot `
    -ReleaseManifest $treeManifestPath `
    -ReleaseManifestSha256 ([string]$treeManifest.sha256) `
    -EnvFile $runtimeEnvFile `
    -DatabasePath $DatabasePath `
    -ReleaseCommit $fullCommit `
    -DeploymentNonce $deploymentNonce `
    -RuntimeConfigSha256 $runtimeConfigSha256 `
    -ProductionConfigSha256 ([string]$productionContract.sha256)
$action = New-ScheduledTaskAction `
    -Execute $releasePythonw `
    -Argument $workerArguments `
    -WorkingDirectory $ApplicationRoot
$operatorUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $operatorUser
$principal = New-ScheduledTaskPrincipal `
    -UserId $operatorUser `
    -LogonType Interactive `
    -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -Disable `
    -RestartCount 255 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw "Scheduled Task appeared during bootstrap; refusing to replace it"
}
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -ErrorAction Stop | Out-Null
Assert-GoldMScheduledTaskAction `
    -TaskName $TaskName `
    -ExpectedExecute $releasePythonw `
    -ExpectedArguments $workerArguments `
    -ExpectedWorkingDirectory $ApplicationRoot
[void](Assert-GoldMWorkerTaskActionContract `
    -Action @((Get-ScheduledTask -TaskName $TaskName).Actions)[0] `
    -ExpectedEnvFile $runtimeEnvFile `
    -ExpectedDatabasePath $DatabasePath `
    -ReleasesRoot $releasesRoot `
    -HelperPythonExecutable $ReleasePython `
    -HelperRepoRoot $ApplicationRoot)
$taskContract = Assert-GoldMScheduledTaskControlContract `
    -TaskName $TaskName `
    -ExpectedUserId $operatorUser `
    -RequireDisabled
$state = [string]$taskContract.State
[void](Invoke-BootstrapReleaseHelper -Arguments @(
    "verify-tree-manifest", "--root", $releaseRoot, "--manifest", $treeManifestPath,
    "--expected-manifest-sha256", [string]$treeManifest.sha256
))

[void](Complete-GoldMMaintenanceLock -Lease $maintenanceLock)
Write-Output "BOOTSTRAP_OK"
Write-Output "commit=$fullCommit"
Write-Output "worker_state=$state"
Write-Output "release=$releaseRoot"
Write-Output "release_manifest_sha256=$($treeManifest.sha256)"
Write-Output "terminal_executable=$TerminalExecutable"
Write-Output "terminal_data_path=$TerminalDataPath"
Write-Output "next=Run deploy-goldm-windows-vm.ps1 -StageOnly, attach the EA to GOLD.i# M15 and save the profile, then run normal deployment."
}
catch {
    $maintenancePrimaryError = $_
    try { Record-GoldMMaintenanceFailure -Lease $maintenanceLock -ErrorRecord $_ }
    catch { Write-Warning "Could not append sanitized maintenance failure evidence" }
    throw $maintenancePrimaryError
}
finally {
    Exit-GoldMMaintenanceLock `
        -Lease $maintenanceLock `
        -PrimaryError $maintenancePrimaryError
}
