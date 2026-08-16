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
    [string]$SafeHandoffManifest = "",
    [string]$SafeHandoffSha256 = "",
    [switch]$StageOnly,
    [string]$MaintenanceRecoveryJournalSha256 = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot "goldm-deployment-common.psm1") -Force

function Invoke-ReleaseHelper {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    return Invoke-GoldMDeploymentHelper `
        -PythonExecutable $script:ReleasePython `
        -RepoRoot $script:appRoot `
        -Arguments $Arguments
}

function Invoke-CutoverPreflight {
    param(
        [switch]$SkipExistingSessionEvidence,
        [string]$PythonExecutable = $script:ReleasePython,
        [string]$HelperRepoRoot = $script:appRoot,
        [string]$ExpectedReleaseCommit = $script:FullCommit,
        [switch]$IgnoreSafeHandoff
    )
    $arguments = @(
        "preflight",
        "--env-file", $script:EnvFile,
        "--database", $script:DatabasePath,
        "--terminal-executable", $script:TerminalExecutable,
        "--terminal-data-path", $script:TerminalDataPath,
        "--release-commit", $ExpectedReleaseCommit
    )
    if ($script:SafeHandoffManifest -and -not $IgnoreSafeHandoff) {
        $arguments += @(
            "--safe-handoff", $script:SafeHandoffManifest,
            "--safe-handoff-sha256", $script:SafeHandoffSha256
        )
    }
    if ($SkipExistingSessionEvidence) {
        $arguments += "--skip-existing-session-evidence"
    }
    return Invoke-GoldMDeploymentHelper `
        -PythonExecutable $PythonExecutable `
        -RepoRoot $HelperRepoRoot `
        -Arguments $arguments
}

function Wait-ExactBrokerPreflight {
    param(
        [int]$TimeoutSeconds = 45,
        [string]$PythonExecutable = $script:ReleasePython,
        [string]$HelperRepoRoot = $script:appRoot,
        [string]$ExpectedReleaseCommit = $script:FullCommit,
        [switch]$IgnoreSafeHandoff
    )
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            return Invoke-CutoverPreflight `
                -SkipExistingSessionEvidence `
                -PythonExecutable $PythonExecutable `
                -HelperRepoRoot $HelperRepoRoot `
                -ExpectedReleaseCommit $ExpectedReleaseCommit `
                -IgnoreSafeHandoff:$IgnoreSafeHandoff
        }
        catch {
            $lastError = $_
        }
        Start-Sleep -Seconds 1
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Exact terminal/account postcondition did not pass within $TimeoutSeconds seconds: $lastError"
}

function Write-ReleaseSealedEvidence {
    param(
        [Parameter(Mandatory = $true)]$Payload,
        [Parameter(Mandatory = $true)][string]$OutputPath
    )
    $temporary = Join-Path $script:DeploymentRoot ("evidence-" + [guid]::NewGuid().ToString("N") + ".tmp")
    try {
        Write-GoldMUtf8NoBomFile `
            -Value ($Payload | ConvertTo-Json -Depth 30) `
            -Path $temporary
        return Invoke-ReleaseHelper -Arguments @(
            "seal-json", "--input", $temporary, "--output", $OutputPath
        )
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

$RepoRoot = Resolve-GoldMDirectory -Path $RepoRoot -Label "repository root"
$maintenanceLock = Enter-GoldMMaintenanceLock `
    -Operation "deploy" `
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
if ($EnvFile) { Assert-GoldMAbsolutePathInput -Path $EnvFile -Label "EnvFile" }
if ($DatabasePath) { Assert-GoldMAbsolutePathInput -Path $DatabasePath -Label "DatabasePath" }
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
$SourceEnvFile = if ($EnvFile) {
    Resolve-GoldMFile -Path $EnvFile -Label "environment file"
}
else {
    Resolve-GoldMFile -Path (Join-Path $RepoRoot ".env") -Label "environment file"
}
$sourceEnvEvidence = Get-GoldMFileEvidence -Path $SourceEnvFile
$runtimeRoot = Join-Path $RepoRoot "runtime_data"
[void](New-GoldMPrivateDirectory -Path $runtimeRoot)
$runtimeConfigRoot = Join-Path $runtimeRoot "config"
[void](New-GoldMPrivateDirectory -Path $runtimeConfigRoot)
$EnvFile = Resolve-GoldMFile `
    -Path (Join-Path $runtimeConfigRoot "runtime.env") `
    -Label "authoritative runtime environment snapshot"
$DatabasePath = if ($DatabasePath) {
    Resolve-GoldMFile -Path $DatabasePath -Label "GOLDM database"
}
else {
    Resolve-GoldMFile -Path (Join-Path $RepoRoot "runtime_data\goldm_signal.db") -Label "GOLDM database"
}
[void](Protect-GoldMPrivateFile -Path $EnvFile)
[void](Protect-GoldMPrivateFile -Path $DatabasePath)
$terminalInstall = Split-Path -Parent $TerminalExecutable
$editorInstall = Split-Path -Parent $MetaEditorPath
if (-not [string]::Equals($terminalInstall, $editorInstall, [StringComparison]::OrdinalIgnoreCase)) {
    throw "TerminalExecutable and MetaEditorPath must belong to the same exact MT5 installation"
}
if ([bool]$SafeHandoffManifest -xor [bool]$SafeHandoffSha256) {
    throw "SafeHandoffManifest and SafeHandoffSha256 must be supplied together"
}
if ($SafeHandoffManifest) {
    throw "Protected-position handoff is disabled for automated cutover; close and reconcile every position first"
}
if ($ReleaseCommit -ne "HEAD" -and $ReleaseCommit -notmatch "^[0-9a-f]{40}$") {
    throw "ReleaseCommit must be HEAD or one full lowercase 40-hex commit SHA"
}
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$operatorUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$originalTaskState = [string]$task.State
if ($originalTaskState -notin @("Running", "Ready", "Disabled")) {
    throw "Scheduled Task state is not safe for deterministic cutover: $originalTaskState"
}
if ($originalTaskState -eq "Disabled") {
    [void](Assert-GoldMScheduledTaskControlContract `
        -TaskName $TaskName `
        -ExpectedUserId $operatorUser `
        -RequireDisabled)
}
else {
    [void](Assert-GoldMScheduledTaskControlContract `
        -TaskName $TaskName `
        -ExpectedUserId $operatorUser `
        -RequireEnabled)
}
if (@($task.Actions).Count -ne 1) {
    throw "Scheduled Task must have exactly one action before deployment"
}
$originalTaskAction = @($task.Actions)[0]
$trustedReleasesRoot = Resolve-GoldMDirectory `
    -Path (Join-Path $RepoRoot "runtime_data\releases") `
    -Label "trusted releases root"
$originalActionContract = Assert-GoldMWorkerTaskActionContract `
    -Action $originalTaskAction `
    -ExpectedEnvFile $EnvFile `
    -ExpectedDatabasePath $DatabasePath `
    -ReleasesRoot $trustedReleasesRoot `
    -HelperPythonExecutable $PythonExecutable `
    -HelperRepoRoot $RepoRoot
$originalProofAuthority = Get-GoldMWorkerProofAuthority `
    -TaskActionContract $originalActionContract
$originalExecute = [string]$originalActionContract.Execute
$originalArguments = [string]$originalActionContract.Arguments
$originalWorkingDirectory = [string]$originalActionContract.WorkingDirectory
$originalReleaseId = [string]$originalActionContract.ReleaseCommit
$originalDeploymentNonce = [string]$originalActionContract.DeploymentNonce
$originalDeploymentNonceSha256 = [string]$originalActionContract.DeploymentNonceSha256

[void](Invoke-GoldMDeploymentHelper `
    -PythonExecutable $PythonExecutable `
    -RepoRoot $RepoRoot `
    -Arguments @(
        "validate-env",
        "--env-file", $EnvFile,
        "--terminal-executable", $TerminalExecutable,
        "--terminal-data-path", $TerminalDataPath
    ))

Set-Location -LiteralPath $RepoRoot
Invoke-GoldMNativeChecked "release_commit_resolve" {
    & git cat-file -e ($ReleaseCommit + "^{commit}")
}
$FullCommit = (& git rev-parse ($ReleaseCommit + "^{commit}")).Trim()
if ($LASTEXITCODE -ne 0 -or $FullCommit -notmatch "^[0-9a-f]{40}$") {
    throw "ReleaseCommit did not resolve to an immutable Git commit"
}

[void](Assert-GoldMPathWithinDirectory `
    -Path $DatabasePath `
    -Directory $runtimeRoot `
    -Label "DatabasePath")
[void](Protect-GoldMDatabaseArtifacts -DatabasePath $DatabasePath)
$releasesRoot = Join-Path $runtimeRoot "releases"
[void](New-GoldMPrivateDirectory -Path $releasesRoot)
$releaseId = ((Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")) + "-" + $FullCommit.Substring(0, 12) + "-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
$ReleaseRoot = Join-Path $releasesRoot $releaseId
[void](New-GoldMPrivateDirectory -Path $ReleaseRoot)
$envStagingRoot = Join-Path $runtimeRoot "env-staging"
[void](New-GoldMPrivateDirectory -Path $envStagingRoot)
$privateEnvStageDirectory = Join-Path $envStagingRoot $releaseId
$privateEnvStageEvidence = Copy-GoldMFileToPrivateStage `
    -Source $SourceEnvFile `
    -StageDirectory $privateEnvStageDirectory `
    -ExpectedSha256 ([string]$sourceEnvEvidence.Sha256)
$stagedSourceEnvFile = [string]$privateEnvStageEvidence.Path
$appRoot = Join-Path $ReleaseRoot "app"
$sourceArchive = Join-Path $ReleaseRoot "source.zip"
New-Item -ItemType Directory -Path $appRoot | Out-Null

Write-Output "phase=prepare_immutable_release"
Invoke-GoldMNativeChecked "git_archive" {
    & git archive --format=zip --output=$sourceArchive $FullCommit
}
Expand-Archive -LiteralPath $sourceArchive -DestinationPath $appRoot
$sealedInputsRoot = Join-Path $ReleaseRoot "sealed-inputs"
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
    -RepoRoot $appRoot
$wheelhouseContract = [pscustomobject]@{
    manifest_sha256 = [string]$wheelhouseStage.ManifestSha256
    lock_sha256 = [string]$wheelhouseStage.LockSha256
}
$wheelhouseLock = Join-Path $stagedWheelhouse "requirements-goldm-live.lock"
$script:ReleasePython = Join-Path $ReleaseRoot ".venv\Scripts\python.exe"
$releasePythonw = Join-Path $ReleaseRoot ".venv\Scripts\pythonw.exe"
Invoke-GoldMNativeChecked "release_venv_create" {
    & $PythonExecutable -I -B -m venv (Join-Path $ReleaseRoot ".venv")
}
foreach ($path in @($ReleasePython, $releasePythonw)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "immutable release virtual environment is incomplete: $path"
    }
}
[void](Assert-GoldMPythonRuntime -PythonExecutable $ReleasePython)
[void](Install-GoldMOfflinePythonRelease `
    -PythonExecutable $ReleasePython `
    -ApplicationRoot $appRoot `
    -WheelhousePath $stagedWheelhouse `
    -RequirementsLock $wheelhouseLock)
[void](Invoke-ReleaseHelper -Arguments @(
    "verify-offline-wheelhouse", "--root", $stagedWheelhouse,
    "--expected-manifest-sha256", $WheelhouseManifestSha256
))
[void](Invoke-ReleaseHelper -Arguments @(
    "validate-env",
    "--env-file", $stagedSourceEnvFile,
    "--terminal-executable", $TerminalExecutable,
    "--terminal-data-path", $TerminalDataPath
))
[void](Assert-GoldMFileMatchesEvidence `
    -Path $stagedSourceEnvFile `
    -Evidence $privateEnvStageEvidence `
    -Label "validated private staged environment")
$productionContract = Invoke-ReleaseHelper -Arguments @(
    "production-input-contract"
)

$releaseMetadata = [ordered]@{
    schemaVersion = 2
    releaseId = $releaseId
    commit = $FullCommit
    sourceArchiveSha256 = Get-GoldMFileSha256 -Path $sourceArchive
    runtimeConfigSha256 = [string]$privateEnvStageEvidence.Sha256
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
    -Value ($releaseMetadata | ConvertTo-Json -Depth 5) `
    -Path (Join-Path $ReleaseRoot "source-metadata.json")
Invoke-GoldMNativeChecked "release_pip_freeze" {
    & $ReleasePython -I -B -m pip --isolated freeze --all | Set-Content -LiteralPath (Join-Path $ReleaseRoot "python-packages.txt") -Encoding UTF8
}

& (Join-Path $appRoot "scripts\verify-goldm-release.ps1") `
    -RepoRoot $appRoot `
    -PythonExecutable $ReleasePython `
    -MetaEditorPath $MetaEditorPath `
    -SkipGitDiffCheck
if ($LASTEXITCODE -ne 0) { throw "immutable release verification failed" }

$stagedEa = Join-Path $appRoot "mt5\Experts\bot-ea\GoldMSniperParity.mq5"
$stagedEx5 = [System.IO.Path]::ChangeExtension($stagedEa, ".ex5")
$compileLog = Join-Path $ReleaseRoot "GoldMSniperParity.compile.log"
if (Test-Path -LiteralPath $stagedEx5) {
    Remove-Item -LiteralPath $stagedEx5 -Force
}
$compileArgumentLine = ConvertTo-GoldMMetaEditorArgumentLine `
    -SourcePath $stagedEa `
    -LogPath $compileLog
$compileProcess = Start-Process `
    -FilePath $MetaEditorPath `
    -ArgumentList $compileArgumentLine `
    -Wait `
    -PassThru `
    -WindowStyle Hidden
if (-not (Test-Path -LiteralPath $compileLog -PathType Leaf)) {
    throw "staged EA compile produced no log"
}
$compileResult = Get-Content -LiteralPath $compileLog -Raw
if (
    # MetaEditor returns the number of successfully compiled source files:
    # one source => 1 on success; a rejected source fixture returns 0.
    $compileProcess.ExitCode -ne 1 -or
    -not (Test-Path -LiteralPath $stagedEx5 -PathType Leaf) -or
    $compileResult -notmatch "Result:\s+0 errors,\s+0 warnings"
) {
    throw "staged EA compile is not clean: $compileLog"
}
$stagedEaSha256 = Get-GoldMFileSha256 -Path $stagedEa
$stagedEx5Sha256 = Get-GoldMFileSha256 -Path $stagedEx5

$treeManifestPath = Join-Path $ReleaseRoot "release-tree-manifest.json"
$treeManifest = Invoke-ReleaseHelper -Arguments @(
    "build-tree-manifest", "--root", $ReleaseRoot, "--output", $treeManifestPath
)
[void](Invoke-ReleaseHelper -Arguments @(
    "verify-tree-manifest", "--root", $ReleaseRoot, "--manifest", $treeManifestPath,
    "--expected-manifest-sha256", [string]$treeManifest.sha256
))

$deploymentsRoot = Join-Path $runtimeRoot "deployments"
[void](New-GoldMPrivateDirectory -Path $deploymentsRoot)
$DeploymentRoot = Join-Path $deploymentsRoot $releaseId
[void](New-GoldMPrivateDirectory -Path $DeploymentRoot)
$logDirectory = Join-Path $TerminalDataPath "MQL5\Logs"
$logCursor = Join-Path $DeploymentRoot "mt5-log-cursor.json"

Write-Output "phase=live_preflight_before_stop"
$preflight = Invoke-CutoverPreflight -SkipExistingSessionEvidence:$StageOnly
$originalAuthorityPreflight = Invoke-CutoverPreflight `
    -SkipExistingSessionEvidence `
    -PythonExecutable ([string]$originalProofAuthority.PythonExecutable) `
    -HelperRepoRoot ([string]$originalProofAuthority.RepoRoot) `
    -ExpectedReleaseCommit ([string]$originalProofAuthority.ReleaseCommit) `
    -IgnoreSafeHandoff
$preflightEvidence = Write-ReleaseSealedEvidence `
    -Payload $preflight `
    -OutputPath (Join-Path $DeploymentRoot "preflight-before-stop.json")

Write-Output "phase=stop_worker"
[void](Disable-GoldMScheduledTaskAndWait -TaskName $TaskName)
[void](Assert-GoldMScheduledTaskControlContract `
    -TaskName $TaskName `
    -ExpectedUserId $operatorUser `
    -RequireDisabled)
$cutoverStarted = $false
$rollbackPrepared = $false
$rollbackSucceeded = $false
$targetEa = Join-Path $TerminalDataPath "MQL5\Experts\bot-ea\GoldMSniperParity.mq5"
$targetEx5 = [System.IO.Path]::ChangeExtension($targetEa, ".ex5")
$runtimeSessionFile = Join-Path $TerminalDataPath "MQL5\Files\goldm_runtime_session.txt"
$backupRoot = Join-Path $DeploymentRoot "rollback"

try {
    Write-Output "phase=final_preflight_after_stop"
    $finalPreflight = Invoke-CutoverPreflight -SkipExistingSessionEvidence:$StageOnly

    [void](New-GoldMPrivateDirectory -Path $backupRoot)
    $databaseBackup = Join-Path $backupRoot "goldm_signal.db"
    $databaseBackupResult = Invoke-ReleaseHelper -Arguments @(
        "backup-db", "--source", $DatabasePath, "--destination", $databaseBackup
    )
    [void](Protect-GoldMPrivateFile -Path $databaseBackup)
    [void](Invoke-ReleaseHelper -Arguments @(
        "verify-db", "--database", $databaseBackup,
        "--expected-sha256", [string]$databaseBackupResult.sha256
    ))
    $envBackup = Join-Path $backupRoot "runtime.env"
    $oldEnvEvidence = Get-GoldMFileEvidence -Path $EnvFile
    Copy-Item -LiteralPath $EnvFile -Destination $envBackup
    [void](Protect-GoldMPrivateFile -Path $envBackup)
    $envBackupEvidence = Assert-GoldMFileMatchesEvidence `
        -Path $envBackup `
        -Evidence $oldEnvEvidence `
        -Label "rollback runtime environment backup"
    $taskXmlBackup = Join-Path $backupRoot "scheduled-task.xml"
    Export-ScheduledTask -TaskName $TaskName | Set-Content -LiteralPath $taskXmlBackup -Encoding Unicode
    [void](Protect-GoldMPrivateFile -Path $taskXmlBackup)

    $oldEaEvidence = Get-GoldMFileEvidence -Path $targetEa
    $oldEx5Evidence = Get-GoldMFileEvidence -Path $targetEx5
    $oldSessionEvidence = Get-GoldMFileEvidence -Path $runtimeSessionFile
    $eaBackup = Join-Path $backupRoot "GoldMSniperParity.mq5"
    $ex5Backup = Join-Path $backupRoot "GoldMSniperParity.ex5"
    $sessionBackup = Join-Path $backupRoot "goldm_runtime_session.txt"
    if ($oldEaEvidence.Exists) { Copy-Item -LiteralPath $targetEa -Destination $eaBackup }
    if ($oldEx5Evidence.Exists) { Copy-Item -LiteralPath $targetEx5 -Destination $ex5Backup }
    if ($oldSessionEvidence.Exists) { Copy-Item -LiteralPath $runtimeSessionFile -Destination $sessionBackup }
    foreach ($member in @($eaBackup, $ex5Backup, $sessionBackup)) {
        if (Test-Path -LiteralPath $member -PathType Leaf) {
            [void](Protect-GoldMPrivateFile -Path $member)
        }
    }
    $eaBackupEvidence = Assert-GoldMFileMatchesEvidence `
        -Path $eaBackup -Evidence $oldEaEvidence -Label "rollback MQ5 backup"
    $ex5BackupEvidence = Assert-GoldMFileMatchesEvidence `
        -Path $ex5Backup -Evidence $oldEx5Evidence -Label "rollback EX5 backup"
    $sessionBackupEvidence = Assert-GoldMFileMatchesEvidence `
        -Path $sessionBackup -Evidence $oldSessionEvidence -Label "rollback runtime-session backup"

    $rollbackPayload = [ordered]@{
        schemaVersion = 2
        purpose = "GOLDM_DEPLOY_ROLLBACK"
        deploymentId = $releaseId
        targetCommit = $FullCommit
        workerReleaseCommit = [string]$originalActionContract.ReleaseCommit
        workerReleaseTreeManifestSha256 = [string]$originalActionContract.ReleaseTreeManifestSha256
        workerRuntimeConfigSha256 = [string]$originalActionContract.RuntimeConfigSha256
        workerProductionConfigSha256 = [string]$originalActionContract.ProductionConfigSha256
        createdAtUtc = [DateTime]::UtcNow.ToString("o")
        releaseTreeManifestSha256 = [string]$treeManifest.sha256
        preflightSha256 = [string]$preflightEvidence.sha256
        safeHandoffSha256 = if ($SafeHandoffSha256) { $SafeHandoffSha256.ToLowerInvariant() } else { "" }
        database = [ordered]@{
            member = "goldm_signal.db"
            sha256 = [string]$databaseBackupResult.sha256
            integrityCheck = [string]$databaseBackupResult.integrity_check
            foreignKeyCheck = [string]$databaseBackupResult.foreign_key_check
            pageCount = [int]$databaseBackupResult.page_count
        }
        environment = [ordered]@{
            member = "runtime.env"
            sha256 = [string]$envBackupEvidence.Sha256
        }
        scheduledTask = [ordered]@{
            name = $TaskName
            previousState = $originalTaskState
            execute = $originalExecute
            arguments = $originalArguments
            workingDirectory = $originalWorkingDirectory
            xmlMember = "scheduled-task.xml"
            xmlSha256 = Get-GoldMFileSha256 -Path $taskXmlBackup
        }
        activeEa = [ordered]@{
            mq5Exists = [bool]$eaBackupEvidence.Exists
            ex5Exists = [bool]$ex5BackupEvidence.Exists
            mq5Member = if ($eaBackupEvidence.Exists) { "GoldMSniperParity.mq5" } else { "" }
            ex5Member = if ($ex5BackupEvidence.Exists) { "GoldMSniperParity.ex5" } else { "" }
            mq5Sha256 = [string]$eaBackupEvidence.Sha256
            ex5Sha256 = [string]$ex5BackupEvidence.Sha256
        }
        runtimeSession = [ordered]@{
            exists = [bool]$sessionBackupEvidence.Exists
            member = if ($sessionBackupEvidence.Exists) { "goldm_runtime_session.txt" } else { "" }
            sha256 = [string]$sessionBackupEvidence.Sha256
        }
    }
    $rollbackEvidence = Write-ReleaseSealedEvidence `
        -Payload $rollbackPayload `
        -OutputPath (Join-Path $backupRoot "rollback-manifest.json")
    [void](Protect-GoldMPrivateFile -Path ([string]$rollbackEvidence.path))
    [void](Protect-GoldMPrivateFile -Path ([string]$rollbackEvidence.sidecar))
    Write-Output "rollback_manifest=$($rollbackEvidence.path)"
    Write-Output "rollback_manifest_sha256=$($rollbackEvidence.sha256)"
    $rollbackPrepared = $true

    [void](Invoke-ReleaseHelper -Arguments @(
        "verify-tree-manifest", "--root", $ReleaseRoot, "--manifest", $treeManifestPath,
        "--expected-manifest-sha256", [string]$treeManifest.sha256
    ))

    Write-Output "phase=cutover"
    $cutoverStarted = $true
    Stop-GoldMExactTerminalGracefully -TerminalExecutable $TerminalExecutable
    # Capture offsets only after the exact terminal has stopped.  Otherwise a
    # CONFIG emitted before this restart could be mistaken for fresh evidence.
    [void](Invoke-ReleaseHelper -Arguments @(
        "capture-log-cursor", "--log-directory", $logDirectory, "--output", $logCursor
    ))
    [void](Assert-GoldMFileMatchesEvidence `
        -Path $stagedSourceEnvFile `
        -Evidence $privateEnvStageEvidence `
        -Label "private staged environment before authoritative snapshot")
    Install-GoldMFileAtomically `
        -Source $stagedSourceEnvFile `
        -Destination $EnvFile `
        -ExpectedSha256 ([string]$privateEnvStageEvidence.Sha256)
    Remove-Item -LiteralPath $stagedSourceEnvFile -Force
    Remove-Item -LiteralPath $privateEnvStageDirectory -Force
    if (Test-Path -LiteralPath $privateEnvStageDirectory) {
        throw "private environment staging leaf was not removed after cutover"
    }
    [void](Protect-GoldMPrivateFile -Path $EnvFile)
    [void](Invoke-ReleaseHelper -Arguments @(
        "validate-env",
        "--env-file", $EnvFile,
        "--terminal-executable", $TerminalExecutable,
        "--terminal-data-path", $TerminalDataPath
    ))
    $runtimeConfigSha256 = Get-GoldMFileSha256 -Path $EnvFile
    if (-not [string]::Equals(
        $runtimeConfigSha256,
        [string]$privateEnvStageEvidence.Sha256,
        [StringComparison]::Ordinal
    )) {
        throw "authoritative runtime environment differs from the private staged input"
    }
    $runtimeSessionEvidence = Invoke-ReleaseHelper -Arguments @(
        "write-runtime-session",
        "--env-file", $EnvFile,
        "--terminal-data-path", $TerminalDataPath
    )
    [void](Protect-GoldMPrivateFile -Path $runtimeSessionFile)
    Install-GoldMFileAtomically `
        -Source $stagedEa `
        -Destination $targetEa `
        -ExpectedSha256 $stagedEaSha256
    Install-GoldMFileAtomically `
        -Source $stagedEx5 `
        -Destination $targetEx5 `
        -ExpectedSha256 $stagedEx5Sha256
    [void](Protect-GoldMPrivateFile -Path $targetEa)
    [void](Protect-GoldMPrivateFile -Path $targetEx5)

    $deploymentNonce = New-GoldMDeploymentNonce
    $deploymentNonceSha256 = Get-GoldMDeploymentNonceSha256 `
        -DeploymentNonce $deploymentNonce
    $workerArguments = New-GoldMWorkerArgumentLine `
        -ReleaseRoot $ReleaseRoot `
        -ApplicationRoot $appRoot `
        -ReleaseManifest $treeManifestPath `
        -ReleaseManifestSha256 ([string]$treeManifest.sha256) `
        -EnvFile $EnvFile `
        -DatabasePath $DatabasePath `
        -ReleaseCommit $FullCommit `
        -DeploymentNonce $deploymentNonce `
        -RuntimeConfigSha256 $runtimeConfigSha256 `
        -ProductionConfigSha256 ([string]$productionContract.sha256)
    $newAction = New-ScheduledTaskAction `
        -Execute $releasePythonw `
        -Argument $workerArguments `
        -WorkingDirectory $appRoot
    Set-ScheduledTask -TaskName $TaskName -Action $newAction -ErrorAction Stop | Out-Null
    Assert-GoldMScheduledTaskAction `
        -TaskName $TaskName `
        -ExpectedExecute $releasePythonw `
        -ExpectedArguments $workerArguments `
        -ExpectedWorkingDirectory $appRoot
    [void](Assert-GoldMWorkerTaskActionContract `
        -Action @((Get-ScheduledTask -TaskName $TaskName).Actions)[0] `
        -ExpectedEnvFile $EnvFile `
        -ExpectedDatabasePath $DatabasePath `
        -ReleasesRoot $releasesRoot `
        -HelperPythonExecutable $ReleasePython `
        -HelperRepoRoot $appRoot)
    [void](Assert-GoldMScheduledTaskControlContract `
        -TaskName $TaskName `
        -ExpectedUserId $operatorUser `
        -RequireDisabled)

    Start-GoldMExactTerminal `
        -TerminalExecutable $TerminalExecutable `
        -TerminalDataPath $TerminalDataPath
    $postTerminal = Wait-ExactBrokerPreflight

    if ($StageOnly) {
        Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
        [void](Assert-GoldMScheduledTaskControlContract `
            -TaskName $TaskName `
            -ExpectedUserId $operatorUser `
            -RequireDisabled)
        $stagePayload = [ordered]@{
            schemaVersion = 1
            purpose = "GOLDM_STAGE_ONLY"
            deploymentId = $releaseId
            commit = $FullCommit
            completedAtUtc = [DateTime]::UtcNow.ToString("o")
            releaseTreeManifestSha256 = [string]$treeManifest.sha256
            runtimeConfigSha256 = $runtimeConfigSha256
            productionConfigSha256 = [string]$productionContract.sha256
            rollbackManifestSha256 = [string]$rollbackEvidence.sha256
            workerState = [string](Get-ScheduledTask -TaskName $TaskName).State
            terminal = $postTerminal.broker
            runtimeSessionFileSha256 = [string]$runtimeSessionEvidence.sha256
            next = "Attach GoldMSniperParity to GOLD.i# M15 and save the profile; live EA reads the atomically written runtime session file. Then run normal deployment."
        }
        $stageEvidence = Write-ReleaseSealedEvidence `
            -Payload $stagePayload `
            -OutputPath (Join-Path $DeploymentRoot "stage-result.json")
        [void](Complete-GoldMMaintenanceLock -Lease $maintenanceLock)
        Write-Output "STAGE_ONLY_OK"
        Write-Output "commit=$FullCommit"
        Write-Output "worker_state=$((Get-ScheduledTask -TaskName $TaskName).State)"
        Write-Output "evidence=$($stageEvidence.path)"
        Write-Output "next=Attach the EA to GOLD.i# M15, save the profile, and rerun without -StageOnly."
        return
    }

    $sessionEvidence = Wait-GoldMSessionEvidence `
        -PythonExecutable $ReleasePython `
        -RepoRoot $appRoot `
        -LogDirectory $logDirectory `
        -CursorPath $logCursor `
        -EnvFile $EnvFile
    [void](Invoke-ReleaseHelper -Arguments @(
        "verify-tree-manifest", "--root", $ReleaseRoot, "--manifest", $treeManifestPath,
        "--expected-manifest-sha256", [string]$treeManifest.sha256
    ))
    $readinessNotBeforeUtc = [DateTime]::UtcNow.ToString("o")
    $taskPostcondition = Start-GoldMScheduledTaskAndVerify `
        -TaskName $TaskName `
        -ExpectedExecute $releasePythonw `
        -ExpectedArguments $workerArguments `
        -ExpectedWorkingDirectory $appRoot
    $telegramReadiness = Wait-GoldMTelegramPollReadiness `
        -PythonExecutable $ReleasePython `
        -RepoRoot $appRoot `
        -DatabasePath $DatabasePath `
        -EnvFile $EnvFile `
        -ExpectedReleaseId $FullCommit `
        -ExpectedDeploymentNonceSha256 $deploymentNonceSha256 `
        -ExpectedReleaseManifestSha256 ([string]$treeManifest.sha256) `
        -ExpectedRuntimeConfigSha256 $runtimeConfigSha256 `
        -ExpectedProductionConfigSha256 ([string]$productionContract.sha256) `
        -NotBeforeUtc $readinessNotBeforeUtc
    $taskPostcondition = Assert-GoldMScheduledTaskRunning `
        -TaskName $TaskName `
        -ExpectedExecute $releasePythonw `
        -ExpectedArguments $workerArguments `
        -ExpectedWorkingDirectory $appRoot
    [void](Assert-GoldMScheduledTaskControlContract `
        -TaskName $TaskName `
        -ExpectedUserId $operatorUser `
        -RequireEnabled)
    $postStartPreflight = Invoke-CutoverPreflight
    # Re-read durable readiness after the broker/session preflight. A newer
    # getUpdates failure (especially Telegram 409) must degrade the earlier
    # success before DEPLOY_OK can be emitted.
    $telegramReadiness = Wait-GoldMTelegramPollReadiness `
        -PythonExecutable $ReleasePython `
        -RepoRoot $appRoot `
        -DatabasePath $DatabasePath `
        -EnvFile $EnvFile `
        -ExpectedReleaseId $FullCommit `
        -ExpectedDeploymentNonceSha256 $deploymentNonceSha256 `
        -ExpectedReleaseManifestSha256 ([string]$treeManifest.sha256) `
        -ExpectedRuntimeConfigSha256 $runtimeConfigSha256 `
        -ExpectedProductionConfigSha256 ([string]$productionContract.sha256) `
        -NotBeforeUtc $readinessNotBeforeUtc
    $taskPostcondition = Assert-GoldMScheduledTaskRunning `
        -TaskName $TaskName `
        -ExpectedExecute $releasePythonw `
        -ExpectedArguments $workerArguments `
        -ExpectedWorkingDirectory $appRoot
    [void](Assert-GoldMScheduledTaskControlContract `
        -TaskName $TaskName `
        -ExpectedUserId $operatorUser `
        -RequireEnabled)

    $resultPayload = [ordered]@{
        schemaVersion = 1
        purpose = "GOLDM_DEPLOY_RESULT"
        deploymentId = $releaseId
        commit = $FullCommit
        completedAtUtc = [DateTime]::UtcNow.ToString("o")
        releaseTreeManifestSha256 = [string]$treeManifest.sha256
        runtimeConfigSha256 = $runtimeConfigSha256
        productionConfigSha256 = [string]$productionContract.sha256
        rollbackManifestSha256 = [string]$rollbackEvidence.sha256
        sessionEvidence = $sessionEvidence
        task = $taskPostcondition
        telegramPollReadiness = $telegramReadiness
        terminal = $postStartPreflight.broker
        targetEa = [ordered]@{
            mq5Sha256 = Get-GoldMFileSha256 -Path $targetEa
            ex5Sha256 = Get-GoldMFileSha256 -Path $targetEx5
        }
        runtimeSessionFileSha256 = [string]$runtimeSessionEvidence.sha256
        liveActivation = $false
    }
    $resultEvidence = Write-ReleaseSealedEvidence `
        -Payload $resultPayload `
        -OutputPath (Join-Path $DeploymentRoot "deployment-result.json")
    [void](Complete-GoldMMaintenanceLock -Lease $maintenanceLock)
    Write-Output "DEPLOY_OK"
    Write-Output "commit=$FullCommit"
    Write-Output "worker_state=$($taskPostcondition.State)"
    Write-Output "terminal_executable=$TerminalExecutable"
    Write-Output "terminal_data_path=$TerminalDataPath"
    Write-Output "release=$ReleaseRoot"
    Write-Output "rollback=$($rollbackEvidence.path)"
    Write-Output "evidence=$($resultEvidence.path)"
}
catch {
    $deploymentError = $_
    Write-Error "Deployment failed; entering fail-closed rollback: $deploymentError" -ErrorAction Continue
    try {
        [void](Disable-GoldMScheduledTaskAndWait -TaskName $TaskName)
        [void](Assert-GoldMScheduledTaskControlContract `
            -TaskName $TaskName `
            -ExpectedUserId $operatorUser `
            -RequireDisabled)
        if ($cutoverStarted -and $rollbackPrepared) {
            # Never trust historical booleans about terminal state. A failing
            # Start-Process or postflight can leave a real process alive even
            # though the script did not record a successful restart. Observe
            # and prove the current state before restoring any file or SQLite.
            Stop-GoldMExactTerminalGracefully -TerminalExecutable $TerminalExecutable
            $remainingTerminals = @(
                Get-GoldMExactTerminalProcesses -TerminalExecutable $TerminalExecutable
            )
            if ($remainingTerminals.Count -ne 0) {
                throw "Exact MT5 terminal is still running; rollback mutation is refused"
            }
            $rollbackLogCursor = Join-Path $DeploymentRoot "rollback-mt5-log-cursor.json"
            [void](Invoke-GoldMDeploymentHelper `
                -PythonExecutable ([string]$originalProofAuthority.PythonExecutable) `
                -RepoRoot ([string]$originalProofAuthority.RepoRoot) `
                -Arguments @(
                    "capture-log-cursor", "--log-directory", $logDirectory,
                    "--output", $rollbackLogCursor
                ))
            [void](Assert-GoldMFileMatchesEvidence `
                -Path $eaBackup -Evidence $eaBackupEvidence -Label "rollback MQ5 backup")
            [void](Assert-GoldMFileMatchesEvidence `
                -Path $ex5Backup -Evidence $ex5BackupEvidence -Label "rollback EX5 backup")
            [void](Assert-GoldMFileMatchesEvidence `
                -Path $sessionBackup -Evidence $sessionBackupEvidence -Label "rollback runtime-session backup")
            [void](Assert-GoldMFileMatchesEvidence `
                -Path $envBackup -Evidence $envBackupEvidence -Label "rollback runtime environment backup")
            Restore-GoldMFile `
                -PreviouslyExisted ([bool]$oldEnvEvidence.Exists) `
                -BackupPath $envBackup `
                -Destination $EnvFile `
                -ExpectedSha256 ([string]$envBackupEvidence.Sha256)
            [void](Protect-GoldMPrivateFile -Path $EnvFile)
            Restore-GoldMFile `
                -PreviouslyExisted ([bool]$oldEaEvidence.Exists) `
                -BackupPath $eaBackup `
                -Destination $targetEa `
                -ExpectedSha256 ([string]$eaBackupEvidence.Sha256)
            Restore-GoldMFile `
                -PreviouslyExisted ([bool]$oldEx5Evidence.Exists) `
                -BackupPath $ex5Backup `
                -Destination $targetEx5 `
                -ExpectedSha256 ([string]$ex5BackupEvidence.Sha256)
            Restore-GoldMFile `
                -PreviouslyExisted ([bool]$oldSessionEvidence.Exists) `
                -BackupPath $sessionBackup `
                -Destination $runtimeSessionFile `
                -ExpectedSha256 ([string]$sessionBackupEvidence.Sha256)
            foreach ($restoredFile in @($targetEa, $targetEx5, $runtimeSessionFile)) {
                if (Test-Path -LiteralPath $restoredFile -PathType Leaf) {
                    [void](Protect-GoldMPrivateFile -Path $restoredFile)
                }
            }
            # The replacement worker may have migrated or mutated SQLite before
            # a later postflight failed. Restore the transactionally captured
            # pre-cutover database while the task is provably stopped; otherwise
            # the old worker could restart against a schema/state it never owned.
            $databaseRestoreResult = Invoke-GoldMDeploymentHelper `
                -PythonExecutable ([string]$originalProofAuthority.PythonExecutable) `
                -RepoRoot ([string]$originalProofAuthority.RepoRoot) `
                -Arguments @(
                    "restore-db",
                    "--backup", $databaseBackup,
                    "--destination", $DatabasePath,
                    "--expected-sha256", [string]$databaseBackupResult.sha256,
                    "--acknowledgement", "RESTORE_STOPPED_GOLDM_DATABASE"
                )
            [void](Invoke-GoldMDeploymentHelper `
                -PythonExecutable ([string]$originalProofAuthority.PythonExecutable) `
                -RepoRoot ([string]$originalProofAuthority.RepoRoot) `
                -Arguments @(
                    "verify-db",
                    "--database", $DatabasePath,
                    "--expected-sha256", [string]$databaseRestoreResult.sha256
                ))
            [void](Protect-GoldMDatabaseArtifacts -DatabasePath $DatabasePath)
            Set-ScheduledTask -TaskName $TaskName -Action $originalTaskAction -ErrorAction Stop | Out-Null
            Assert-GoldMScheduledTaskAction `
                -TaskName $TaskName `
                -ExpectedExecute $originalExecute `
                -ExpectedArguments $originalArguments `
                -ExpectedWorkingDirectory $originalWorkingDirectory
            [void](Assert-GoldMWorkerTaskActionContract `
                -Action (@((Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop).Actions)[0]) `
                -ExpectedEnvFile $EnvFile `
                -ExpectedDatabasePath $DatabasePath `
                -ReleasesRoot $trustedReleasesRoot `
                -HelperPythonExecutable ([string]$originalProofAuthority.PythonExecutable) `
                -HelperRepoRoot ([string]$originalProofAuthority.RepoRoot))
            Start-GoldMExactTerminal `
                -TerminalExecutable $TerminalExecutable `
                -TerminalDataPath $TerminalDataPath
            [void](Wait-ExactBrokerPreflight `
                -PythonExecutable ([string]$originalProofAuthority.PythonExecutable) `
                -HelperRepoRoot ([string]$originalProofAuthority.RepoRoot) `
                -ExpectedReleaseCommit ([string]$originalProofAuthority.ReleaseCommit) `
                -IgnoreSafeHandoff)
            if (-not $StageOnly -and $originalTaskState -eq "Running") {
                [void](Wait-GoldMSessionEvidence `
                    -PythonExecutable ([string]$originalProofAuthority.PythonExecutable) `
                    -RepoRoot ([string]$originalProofAuthority.RepoRoot) `
                    -LogDirectory $logDirectory `
                    -CursorPath $rollbackLogCursor `
                    -EnvFile $EnvFile)
            }
        }
        else {
            # The terminal was not mutated, but the last preflight failed.
            # Re-prove its exact account in every mode and the existing EA
            # session before allowing an old worker to return.
            [void](Wait-ExactBrokerPreflight `
                -PythonExecutable ([string]$originalProofAuthority.PythonExecutable) `
                -HelperRepoRoot ([string]$originalProofAuthority.RepoRoot) `
                -ExpectedReleaseCommit ([string]$originalProofAuthority.ReleaseCommit) `
                -IgnoreSafeHandoff)
            if (-not $StageOnly) {
                [void](Invoke-CutoverPreflight `
                    -PythonExecutable ([string]$originalProofAuthority.PythonExecutable) `
                    -HelperRepoRoot ([string]$originalProofAuthority.RepoRoot) `
                    -ExpectedReleaseCommit ([string]$originalProofAuthority.ReleaseCommit) `
                    -IgnoreSafeHandoff)
            }
        }
        if (-not $StageOnly) {
            if ($originalTaskState -eq "Running") {
                if (-not $originalReleaseId) {
                    throw "Original worker action has no exact --release-id binding; rollback cannot prove Telegram readiness"
                }
                $rollbackReadinessNotBeforeUtc = [DateTime]::UtcNow.ToString("o")
                [void](Start-GoldMScheduledTaskAndVerify `
                    -TaskName $TaskName `
                    -ExpectedExecute $originalExecute `
                    -ExpectedArguments $originalArguments `
                    -ExpectedWorkingDirectory $originalWorkingDirectory)
                [void](Wait-GoldMTelegramPollReadiness `
                    -PythonExecutable ([string]$originalProofAuthority.PythonExecutable) `
                    -RepoRoot ([string]$originalProofAuthority.RepoRoot) `
                    -DatabasePath $DatabasePath `
                    -EnvFile $EnvFile `
                    -ExpectedReleaseId $originalReleaseId `
                    -ExpectedDeploymentNonceSha256 $originalDeploymentNonceSha256 `
                    -ExpectedReleaseManifestSha256 ([string]$originalActionContract.ReleaseTreeManifestSha256) `
                    -ExpectedRuntimeConfigSha256 ([string]$originalActionContract.RuntimeConfigSha256) `
                    -ExpectedProductionConfigSha256 ([string]$originalActionContract.ProductionConfigSha256) `
                    -NotBeforeUtc $rollbackReadinessNotBeforeUtc)
                [void](Assert-GoldMScheduledTaskRunning `
                    -TaskName $TaskName `
                    -ExpectedExecute $originalExecute `
                    -ExpectedArguments $originalArguments `
                    -ExpectedWorkingDirectory $originalWorkingDirectory)
                [void](Invoke-CutoverPreflight `
                    -PythonExecutable ([string]$originalProofAuthority.PythonExecutable) `
                    -HelperRepoRoot ([string]$originalProofAuthority.RepoRoot) `
                    -ExpectedReleaseCommit ([string]$originalProofAuthority.ReleaseCommit) `
                    -IgnoreSafeHandoff)
                [void](Wait-GoldMTelegramPollReadiness `
                    -PythonExecutable ([string]$originalProofAuthority.PythonExecutable) `
                    -RepoRoot ([string]$originalProofAuthority.RepoRoot) `
                    -DatabasePath $DatabasePath `
                    -EnvFile $EnvFile `
                    -ExpectedReleaseId $originalReleaseId `
                    -ExpectedDeploymentNonceSha256 $originalDeploymentNonceSha256 `
                    -ExpectedReleaseManifestSha256 ([string]$originalActionContract.ReleaseTreeManifestSha256) `
                    -ExpectedRuntimeConfigSha256 ([string]$originalActionContract.RuntimeConfigSha256) `
                    -ExpectedProductionConfigSha256 ([string]$originalActionContract.ProductionConfigSha256) `
                    -NotBeforeUtc $rollbackReadinessNotBeforeUtc)
                [void](Assert-GoldMScheduledTaskRunning `
                    -TaskName $TaskName `
                    -ExpectedExecute $originalExecute `
                    -ExpectedArguments $originalArguments `
                    -ExpectedWorkingDirectory $originalWorkingDirectory)
                [void](Assert-GoldMScheduledTaskControlContract `
                    -TaskName $TaskName `
                    -ExpectedUserId $operatorUser `
                    -RequireEnabled)
            }
            elseif ($originalTaskState -eq "Disabled") {
                Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
                [void](Assert-GoldMScheduledTaskControlContract `
                    -TaskName $TaskName `
                    -ExpectedUserId $operatorUser `
                    -RequireDisabled)
            }
            else {
                Enable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
                [void](Assert-GoldMScheduledTaskControlContract `
                    -TaskName $TaskName `
                    -ExpectedUserId $operatorUser `
                    -RequireEnabled)
                $restoredTaskState = [string](Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop).State
                if ($restoredTaskState -ne "Ready") {
                    throw "Rollback could not restore original Ready worker state (state=$restoredTaskState)"
                }
            }
        }
        else {
            Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null
        }
        $rollbackSucceeded = $true
    }
    catch {
        Write-Error "Rollback could not prove all postconditions; worker remains stopped: $_" -ErrorAction Continue
        try {
            [void](Disable-GoldMScheduledTaskAndWait -TaskName $TaskName)
        }
        catch {
            # Preserve disable-before-stop ordering even in best-effort cleanup.
            Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null
            Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        }
    }
    if ($rollbackPrepared) {
        try {
            $failurePayload = [ordered]@{
                schemaVersion = 1
                purpose = "GOLDM_DEPLOY_FAILURE"
                deploymentId = $releaseId
                commit = $FullCommit
                failedAtUtc = [DateTime]::UtcNow.ToString("o")
                rollbackSucceeded = $rollbackSucceeded
                rollbackManifest = [string]$rollbackEvidence.path
                rollbackManifestSha256 = [string]$rollbackEvidence.sha256
                workerState = [string](Get-ScheduledTask -TaskName $TaskName).State
                error = [string]$deploymentError.Exception.Message
            }
            [void](Write-ReleaseSealedEvidence `
                -Payload $failurePayload `
                -OutputPath (Join-Path $DeploymentRoot "deployment-failure.json"))
        }
        catch {
            Write-Error "Could not seal failure evidence: $_" -ErrorAction Continue
        }
    }
    throw $deploymentError
}
}
catch {
    $maintenancePrimaryError = $_
    $journalEvidencePath = ""
    $journalEvidenceSha256 = ""
    if (Get-Variable -Name rollbackEvidence -ErrorAction SilentlyContinue) {
        $journalEvidencePath = [string]$rollbackEvidence.path
        $journalEvidenceSha256 = [string]$rollbackEvidence.sha256
    }
    try {
        Record-GoldMMaintenanceFailure `
            -Lease $maintenanceLock `
            -ErrorRecord $_ `
            -EvidencePath $journalEvidencePath `
            -EvidenceSha256 $journalEvidenceSha256
    }
    catch { Write-Warning "Could not append sanitized maintenance failure evidence" }
    throw $maintenancePrimaryError
}
finally {
    Exit-GoldMMaintenanceLock `
        -Lease $maintenanceLock `
        -PrimaryError $maintenancePrimaryError
}
