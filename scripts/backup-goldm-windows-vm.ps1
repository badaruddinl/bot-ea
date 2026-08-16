param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TaskName = "goldm telegram worker",
    [Parameter(Mandatory = $true)][string]$PythonExecutable,
    [Parameter(Mandatory = $true)][string]$PythonSha256,
    [Parameter(Mandatory = $true)][string]$TerminalExecutable,
    [Parameter(Mandatory = $true)][string]$TerminalDataPath,
    [string]$EnvFile = "",
    [string]$DatabasePath = "",
    [string]$OutputRoot = "",
    [string]$MaintenanceRecoveryJournalSha256 = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot "goldm-deployment-common.psm1") -Force

$RepoRoot = Resolve-GoldMDirectory -Path $RepoRoot -Label "repository root"
$maintenanceLock = Enter-GoldMMaintenanceLock `
    -Operation "backup" `
    -RecoveryJournalSha256 $MaintenanceRecoveryJournalSha256
$maintenancePrimaryError = $null
try {
foreach ($binding in @(
    @($PythonExecutable, "PythonExecutable"),
    @($TerminalExecutable, "TerminalExecutable"),
    @($TerminalDataPath, "TerminalDataPath")
)) {
    Assert-GoldMAbsolutePathInput -Path ([string]$binding[0]) -Label ([string]$binding[1])
}
if ($EnvFile) { Assert-GoldMAbsolutePathInput -Path $EnvFile -Label "EnvFile" }
if ($DatabasePath) { Assert-GoldMAbsolutePathInput -Path $DatabasePath -Label "DatabasePath" }
if ($OutputRoot) { Assert-GoldMAbsolutePathInput -Path $OutputRoot -Label "OutputRoot" }
$pythonContract = Assert-GoldMPythonInterpreter `
    -PythonExecutable $PythonExecutable `
    -ExpectedSha256 $PythonSha256
$PythonExecutable = $pythonContract.Path
$TerminalExecutable = Resolve-GoldMFile -Path $TerminalExecutable -Label "terminal executable"
$TerminalDataPath = Resolve-GoldMDirectory -Path $TerminalDataPath -Label "terminal data path"
[void](Assert-GoldMStandardTerminalTopology `
    -TerminalExecutable $TerminalExecutable `
    -TerminalDataPath $TerminalDataPath)
$runtimeRoot = Join-Path $RepoRoot "runtime_data"
[void](New-GoldMPrivateDirectory -Path $runtimeRoot)
$runtimeConfigRoot = Join-Path $runtimeRoot "config"
[void](New-GoldMPrivateDirectory -Path $runtimeConfigRoot)
$runtimeEnvFile = [System.IO.Path]::GetFullPath(
    (Join-Path $runtimeConfigRoot "runtime.env")
)
if (
    $EnvFile -and
    -not [string]::Equals(
        [System.IO.Path]::GetFullPath($EnvFile),
        $runtimeEnvFile,
        [StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "EnvFile must be the task-bound private runtime snapshot: $runtimeEnvFile"
}
$EnvFile = Resolve-GoldMFile `
    -Path $runtimeEnvFile `
    -Label "task-bound runtime environment snapshot"
$DatabasePath = if ($DatabasePath) {
    Resolve-GoldMFile -Path $DatabasePath -Label "GOLDM database"
}
else {
    Resolve-GoldMFile -Path (Join-Path $RepoRoot "runtime_data\goldm_signal.db") -Label "GOLDM database"
}
$usesDefaultOutputRoot = -not [bool]$OutputRoot
$OutputRoot = if ($OutputRoot) {
    [System.IO.Path]::GetFullPath($OutputRoot)
}
else {
    Join-Path $RepoRoot "runtime_data\operator-backups"
}

[void](Assert-GoldMPathWithinDirectory `
    -Path $DatabasePath `
    -Directory $runtimeRoot `
    -Label "DatabasePath")
[void](Protect-GoldMDatabaseArtifacts -DatabasePath $DatabasePath)
$outputRootParent = Resolve-GoldMDirectory `
    -Path (Split-Path -Parent $OutputRoot) `
    -Label "backup output parent"
Assert-GoldMNoReparsePath -Path $OutputRoot -Label "backup output root"
if (
    -not $usesDefaultOutputRoot -and
    -not [string]::Equals(
        (Split-Path -Leaf $OutputRoot),
        "goldm-operator-backups",
        [StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "Custom OutputRoot must be a dedicated leaf named goldm-operator-backups"
}
if (-not $usesDefaultOutputRoot) {
    foreach ($systemRoot in @(
        $env:windir,
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)}
    )) {
        if (-not $systemRoot) { continue }
        $systemPrefix = [System.IO.Path]::GetFullPath($systemRoot).TrimEnd('\') + '\'
        if ($OutputRoot.StartsWith($systemPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Custom OutputRoot cannot be placed below a Windows or Program Files system tree"
        }
    }
}
$outputRootCreated = $false
if (-not (Test-Path -LiteralPath $OutputRoot)) {
    New-Item -ItemType Directory -Path $OutputRoot -ErrorAction Stop | Out-Null
    $outputRootCreated = $true
}
$OutputRoot = Resolve-GoldMDirectory -Path $OutputRoot -Label "dedicated backup output root"
if ($usesDefaultOutputRoot -or $outputRootCreated) {
    # The default is an app-owned runtime leaf; a custom directory may be
    # protected only when this run just created that exact dedicated leaf.
    [void](New-GoldMPrivateDirectory -Path $OutputRoot)
}
$outputMarker = Join-Path $OutputRoot ".goldm-operator-backup-root"
if (Test-Path -LiteralPath $outputMarker -PathType Leaf) {
    $outputMarker = Resolve-GoldMFile -Path $outputMarker -Label "backup output ownership marker"
    if ((Get-Content -LiteralPath $outputMarker -Raw).Trim() -ne "GOLDM_OPERATOR_BACKUP_ROOT_V1") {
        throw "Custom backup output ownership marker is invalid"
    }
}
elseif (-not $usesDefaultOutputRoot -and -not $outputRootCreated) {
    throw "Existing custom OutputRoot lacks the exact GOLDM ownership marker"
}
else {
    Write-GoldMUtf8NoBomFile `
        -Value "GOLDM_OPERATOR_BACKUP_ROOT_V1`n" `
        -Path $outputMarker
}
[void](Protect-GoldMPrivateFile -Path $outputMarker)
Protect-GoldMPrivateFile -Path $EnvFile
Protect-GoldMPrivateFile -Path $DatabasePath

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$operatorUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskState = [string]$task.State
if ($taskState -notin @("Running", "Ready", "Disabled")) {
    throw "Scheduled Task state is not safe for backup: $taskState"
}
if ($taskState -eq "Disabled") {
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
    throw "Scheduled Task must have exactly one action"
}
$releasesRoot = Resolve-GoldMDirectory `
    -Path (Join-Path $runtimeRoot "releases") `
    -Label "trusted releases root"
$initialTaskAction = Assert-GoldMWorkerTaskActionContract `
    -Action (@($task.Actions)[0]) `
    -ExpectedEnvFile $EnvFile `
    -ExpectedDatabasePath $DatabasePath `
    -ReleasesRoot $releasesRoot `
    -HelperPythonExecutable $PythonExecutable `
    -HelperRepoRoot $RepoRoot
$workerProofAuthority = Get-GoldMWorkerProofAuthority `
    -TaskActionContract $initialTaskAction
[void](Invoke-GoldMDeploymentHelper `
    -PythonExecutable ([string]$workerProofAuthority.PythonExecutable) `
    -RepoRoot ([string]$workerProofAuthority.RepoRoot) `
    -Arguments @(
        "validate-env",
        "--env-file", $EnvFile,
        "--terminal-executable", $TerminalExecutable,
        "--terminal-data-path", $TerminalDataPath
    ))
$commit = (& git -C $RepoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $commit -notmatch "^[0-9a-f]{40}$") {
    throw "Cannot resolve repository commit for backup evidence"
}
$preflightArguments = @(
    "preflight",
    "--env-file", $EnvFile,
    "--database", $DatabasePath,
    "--terminal-executable", $TerminalExecutable,
    "--terminal-data-path", $TerminalDataPath,
    "--release-commit", [string]$workerProofAuthority.ReleaseCommit,
    "--skip-existing-session-evidence"
)
[void](Invoke-GoldMDeploymentHelper `
    -PythonExecutable ([string]$workerProofAuthority.PythonExecutable) `
    -RepoRoot ([string]$workerProofAuthority.RepoRoot) `
    -Arguments $preflightArguments)

$backupId = ((Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")) + "-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
$backupRoot = Join-Path $OutputRoot $backupId
New-Item -ItemType Directory -Path $backupRoot -ErrorAction Stop | Out-Null
[void](New-GoldMPrivateDirectory -Path $backupRoot)

$databaseBackup = Join-Path $backupRoot "goldm_signal.db"
$databaseResult = Invoke-GoldMDeploymentHelper `
    -PythonExecutable ([string]$workerProofAuthority.PythonExecutable) `
    -RepoRoot ([string]$workerProofAuthority.RepoRoot) `
    -Arguments @("backup-db", "--source", $DatabasePath, "--destination", $databaseBackup)
[void](Invoke-GoldMDeploymentHelper `
    -PythonExecutable ([string]$workerProofAuthority.PythonExecutable) `
    -RepoRoot ([string]$workerProofAuthority.RepoRoot) `
    -Arguments @(
        "verify-db", "--database", $databaseBackup,
        "--expected-sha256", [string]$databaseResult.sha256
    ))
[void](Invoke-GoldMDeploymentHelper `
    -PythonExecutable ([string]$workerProofAuthority.PythonExecutable) `
    -RepoRoot ([string]$workerProofAuthority.RepoRoot) `
    -Arguments @(
        "inspect-db", "--database", $databaseBackup, "--require-quiescent"
    ))
Protect-GoldMPrivateFile -Path $databaseBackup

$envBackup = Join-Path $backupRoot "runtime.env"
Copy-Item -LiteralPath $EnvFile -Destination $envBackup
Protect-GoldMPrivateFile -Path $envBackup
$taskXml = Join-Path $backupRoot "scheduled-task.xml"
$targetEa = Join-Path $TerminalDataPath "MQL5\Experts\bot-ea\GoldMSniperParity.mq5"
$targetEx5 = [System.IO.Path]::ChangeExtension($targetEa, ".ex5")
$runtimeSessionFile = Join-Path $TerminalDataPath "MQL5\Files\goldm_runtime_session.txt"
$eaEvidence = Get-GoldMFileEvidence -Path $targetEa
$ex5Evidence = Get-GoldMFileEvidence -Path $targetEx5
$sessionEvidence = Get-GoldMFileEvidence -Path $runtimeSessionFile
$eaBackup = Join-Path $backupRoot "GoldMSniperParity.mq5"
$ex5Backup = Join-Path $backupRoot "GoldMSniperParity.ex5"
$sessionBackup = Join-Path $backupRoot "goldm_runtime_session.txt"
if ($eaEvidence.Exists) {
    Copy-Item -LiteralPath $targetEa -Destination $eaBackup
    Protect-GoldMPrivateFile -Path $eaBackup
}
if ($ex5Evidence.Exists) {
    Copy-Item -LiteralPath $targetEx5 -Destination $ex5Backup
    Protect-GoldMPrivateFile -Path $ex5Backup
}
if ($sessionEvidence.Exists) {
    Copy-Item -LiteralPath $runtimeSessionFile -Destination $sessionBackup
    Protect-GoldMPrivateFile -Path $sessionBackup
}
$eaBackupEvidence = Get-GoldMFileEvidence -Path $eaBackup
$ex5BackupEvidence = Get-GoldMFileEvidence -Path $ex5Backup
$sessionBackupEvidence = Get-GoldMFileEvidence -Path $sessionBackup
foreach ($pair in @(
    [pscustomobject]@{ Source = $eaEvidence; Member = $eaBackupEvidence; Label = "MQ5" },
    [pscustomobject]@{ Source = $ex5Evidence; Member = $ex5BackupEvidence; Label = "EX5" },
    [pscustomobject]@{ Source = $sessionEvidence; Member = $sessionBackupEvidence; Label = "runtime session" }
)) {
    $sourceEvidence = $pair.Source
    $memberEvidence = $pair.Member
    if (
        [bool]$sourceEvidence.Exists -ne [bool]$memberEvidence.Exists -or
        (
            [bool]$sourceEvidence.Exists -and
            -not [string]::Equals(
                [string]$sourceEvidence.Sha256,
                [string]$memberEvidence.Sha256,
                [StringComparison]::OrdinalIgnoreCase
            )
        )
    ) {
        throw "Backup copy does not match the captured $($pair.Label) source"
    }
}

# The broker and live database are external to SQLite's online snapshot.  Re-prove
# exact account identity, a flat broker book, and current DB quiescence after all
# snapshot/copy work so BACKUP_OK cannot rely only on a stale pre-snapshot view.
[void](Invoke-GoldMDeploymentHelper `
    -PythonExecutable ([string]$workerProofAuthority.PythonExecutable) `
    -RepoRoot ([string]$workerProofAuthority.RepoRoot) `
    -Arguments $preflightArguments)

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$taskState = [string]$task.State
if ($taskState -notin @("Running", "Ready", "Disabled")) {
    throw "Scheduled Task state changed to an unsafe value during backup: $taskState"
}
if ($taskState -eq "Disabled") {
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
    throw "Scheduled Task action count changed during backup"
}
$finalTaskAction = Assert-GoldMWorkerTaskActionContract `
    -Action (@($task.Actions)[0]) `
    -ExpectedEnvFile $EnvFile `
    -ExpectedDatabasePath $DatabasePath `
    -ReleasesRoot $releasesRoot `
    -HelperPythonExecutable ([string]$workerProofAuthority.PythonExecutable) `
    -HelperRepoRoot ([string]$workerProofAuthority.RepoRoot)
foreach ($property in @("Execute", "Arguments", "WorkingDirectory")) {
    if (-not [string]::Equals(
        [string]$initialTaskAction.$property,
        [string]$finalTaskAction.$property,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Scheduled Task action changed during backup: $property"
    }
}
Export-ScheduledTask -TaskName $TaskName |
    Set-Content -LiteralPath $taskXml -Encoding Unicode
Protect-GoldMPrivateFile -Path $taskXml

$action = $finalTaskAction
$manifest = [ordered]@{
    schemaVersion = 2
    purpose = "GOLDM_OPERATOR_BACKUP"
    backupId = $backupId
    createdAtUtc = [DateTime]::UtcNow.ToString("o")
    repositoryCommit = $commit
    workerReleaseCommit = [string]$finalTaskAction.ReleaseCommit
    workerReleaseTreeManifestSha256 = [string]$finalTaskAction.ReleaseTreeManifestSha256
    workerRuntimeConfigSha256 = [string]$finalTaskAction.RuntimeConfigSha256
    workerProductionConfigSha256 = [string]$finalTaskAction.ProductionConfigSha256
    database = [ordered]@{
        member = "goldm_signal.db"
        sha256 = [string]$databaseResult.sha256
        integrityCheck = [string]$databaseResult.integrity_check
        foreignKeyCheck = [string]$databaseResult.foreign_key_check
        pageCount = [long]$databaseResult.page_count
    }
    environment = [ordered]@{
        member = "runtime.env"
        sha256 = Get-GoldMFileSha256 -Path $envBackup
    }
    scheduledTask = [ordered]@{
        name = $TaskName
        state = [string]$task.State
        execute = [string]$action.Execute
        arguments = [string]$action.Arguments
        workingDirectory = [string]$action.WorkingDirectory
        xmlMember = "scheduled-task.xml"
        xmlSha256 = Get-GoldMFileSha256 -Path $taskXml
    }
    terminal = [ordered]@{
        executable = $TerminalExecutable
        dataPath = $TerminalDataPath
    }
    activeEa = [ordered]@{
        mq5Exists = [bool]$eaBackupEvidence.Exists
        ex5Exists = [bool]$ex5BackupEvidence.Exists
        mq5Member = if ($eaBackupEvidence.Exists) { "GoldMSniperParity.mq5" } else { $null }
        ex5Member = if ($ex5BackupEvidence.Exists) { "GoldMSniperParity.ex5" } else { $null }
        mq5Sha256 = [string]$eaBackupEvidence.Sha256
        ex5Sha256 = [string]$ex5BackupEvidence.Sha256
    }
    runtimeSession = [ordered]@{
        exists = [bool]$sessionBackupEvidence.Exists
        member = if ($sessionBackupEvidence.Exists) { "goldm_runtime_session.txt" } else { $null }
        sha256 = [string]$sessionBackupEvidence.Sha256
    }
}
$sealed = Write-GoldMSealedEvidence `
    -Payload $manifest `
    -OutputPath (Join-Path $backupRoot "backup-manifest.json") `
    -PythonExecutable $PythonExecutable `
    -RepoRoot $RepoRoot
Protect-GoldMPrivateFile -Path ([string]$sealed.path)
Protect-GoldMPrivateFile -Path (([string]$sealed.path) + ".sha256")

# Final broker/account/flat-book proof is deliberately the last external-state
# read before BACKUP_OK.  The earlier post-copy proof guards the artifact build;
# this one closes the sealing window and fails rather than blessing stale state.
[void](Invoke-GoldMDeploymentHelper `
    -PythonExecutable ([string]$workerProofAuthority.PythonExecutable) `
    -RepoRoot ([string]$workerProofAuthority.RepoRoot) `
    -Arguments $preflightArguments)

[void](Complete-GoldMMaintenanceLock -Lease $maintenanceLock)
Write-Output "BACKUP_OK"
Write-Output "database_backup_mode=sqlite_online_backup_api"
Write-Output "task_was_not_stopped=true"
Write-Output "manifest=$($sealed.path)"
Write-Output "manifest_sha256=$($sealed.sha256)"
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
