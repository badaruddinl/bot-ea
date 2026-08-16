param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TaskName = "goldm telegram worker",
    [Parameter(Mandatory = $true)][string]$PythonExecutable,
    [Parameter(Mandatory = $true)][string]$PythonSha256,
    [Parameter(Mandatory = $true)][string]$TerminalExecutable,
    [Parameter(Mandatory = $true)][string]$TerminalDataPath,
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [Parameter(Mandatory = $true)][string]$ManifestSha256,
    [Parameter(Mandatory = $true)][string]$Acknowledgement,
    [string]$EnvFile = "",
    [string]$DatabasePath = "",
    [switch]$RestoreDatabase,
    [switch]$RestoreEnvironment,
    [switch]$RestoreRuntimeSession,
    [switch]$RestoreEa,
    [switch]$RestoreTaskAction,
    [switch]$StartWorker,
    [string]$MaintenanceRecoveryJournalSha256 = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot "goldm-deployment-common.psm1") -Force

function Resolve-BackupMember {
    param([Parameter(Mandatory = $true)][string]$Member)
    if (
        [System.IO.Path]::IsPathRooted($Member) -or
        $Member -notmatch "^[A-Za-z0-9][A-Za-z0-9._-]*$"
    ) {
        throw "Manifest backup member must be one safe flat relative filename"
    }
    $candidate = Join-Path $script:ManifestRoot $Member
    $item = Get-Item -LiteralPath $candidate -Force -ErrorAction Stop
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Manifest backup member cannot be a symbolic link or reparse point"
    }
    $resolved = Resolve-GoldMFile -Path $candidate -Label "manifest backup member"
    $canonicalRoot = [System.IO.Path]::GetFullPath($script:ManifestRoot).TrimEnd('\')
    $rootWithSeparator = $canonicalRoot + '\'
    $canonicalMember = [System.IO.Path]::GetFullPath($resolved)
    if (
        -not $canonicalMember.StartsWith($rootWithSeparator, [StringComparison]::OrdinalIgnoreCase) -or
        -not [string]::Equals(
            (Split-Path -Parent $canonicalMember),
            $canonicalRoot,
            [StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "Manifest backup member escapes its sealed backup directory"
    }
    return $canonicalMember
}

function Assert-BackupHash {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256
    )
    if ($ExpectedSha256 -notmatch "^[0-9a-fA-F]{64}$") {
        throw "Manifest contains an invalid SHA-256"
    }
    $actual = Get-GoldMFileSha256 -Path $Path
    if (-not $actual.Equals($ExpectedSha256, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Backup member SHA-256 mismatch: $Path"
    }
}

function Copy-GoldMExternalBackupToPrivateStage {
    param(
        [Parameter(Mandatory = $true)][string]$ExternalManifestPath,
        [Parameter(Mandatory = $true)][string]$StagingRoot
    )

    $externalManifestItem = Get-Item `
        -LiteralPath $ExternalManifestPath `
        -Force `
        -ErrorAction Stop
    if (
        $externalManifestItem.PSIsContainer -or
        ($externalManifestItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "The external sealed backup manifest must be a regular non-reparse file"
    }
    $manifestName = [string]$externalManifestItem.Name
    if ($manifestName -notin @("backup-manifest.json", "rollback-manifest.json")) {
        throw "The external sealed backup manifest has an unsupported filename"
    }

    $externalRootItem = Get-Item `
        -LiteralPath (Split-Path -Parent $externalManifestItem.FullName) `
        -Force `
        -ErrorAction Stop
    if (
        -not $externalRootItem.PSIsContainer -or
        ($externalRootItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
    ) {
        throw "The external sealed backup directory must be a regular non-reparse directory"
    }
    $externalRoot = Resolve-GoldMDirectory `
        -Path $externalRootItem.FullName `
        -Label "external sealed backup directory"
    [void](Assert-GoldMReadOnlyFlatDirectory -Path $externalRoot)

    $externalItems = @(Get-ChildItem -LiteralPath $externalRoot -Force)
    $externalNames = [System.Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($externalItem in $externalItems) {
        if (
            $externalItem.PSIsContainer -or
            ($externalItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
            -not (Test-Path -LiteralPath $externalItem.FullName -PathType Leaf)
        ) {
            throw "External sealed backup directory contains a non-file or reparse entry"
        }
        if (
            [string]$externalItem.Name -notmatch "^[A-Za-z0-9][A-Za-z0-9._-]*$" -or
            -not $externalNames.Add([string]$externalItem.Name)
        ) {
            throw "External sealed backup directory contains an unsafe or duplicate filename"
        }
    }
    if (
        -not $externalNames.Contains($manifestName) -or
        -not $externalNames.Contains($manifestName + ".sha256")
    ) {
        throw "External sealed backup directory lacks its exact manifest/sidecar pair"
    }
    if (Test-Path -LiteralPath $StagingRoot) {
        throw "Private restore staging directory already exists"
    }
    [void](New-GoldMPrivateDirectory -Path $StagingRoot)

    foreach ($externalItem in $externalItems) {
        # Re-resolve immediately before the only external read. The trusted
        # manifest/member hashes below authenticate the immutable staged bytes.
        $sourceItem = Get-Item `
            -LiteralPath $externalItem.FullName `
            -Force `
            -ErrorAction Stop
        if (
            $sourceItem.PSIsContainer -or
            ($sourceItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 -or
            -not [string]::Equals(
                [string]$sourceItem.Name,
                [string]$externalItem.Name,
                [StringComparison]::Ordinal
            )
        ) {
            throw "External backup entry changed type or identity while staging"
        }
        $sourcePath = Resolve-GoldMFile `
            -Path $sourceItem.FullName `
            -Label "external backup staging source"
        if (-not [string]::Equals(
            (Split-Path -Parent $sourcePath),
            $externalRoot,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "External backup staging source escaped its flat directory"
        }
        $destination = Join-Path $StagingRoot ([string]$externalItem.Name)
        Copy-Item `
            -LiteralPath $sourcePath `
            -Destination $destination `
            -ErrorAction Stop
        [void](Protect-GoldMPrivateFile -Path $destination)
    }

    $resolvedStagingRoot = Resolve-GoldMDirectory `
        -Path $StagingRoot `
        -Label "private restore staging directory"
    [void](Assert-GoldMReadOnlyFlatDirectory -Path $resolvedStagingRoot)
    return [pscustomobject]@{
        Root = $resolvedStagingRoot
        ManifestPath = Resolve-GoldMFile `
            -Path (Join-Path $resolvedStagingRoot $manifestName) `
            -Label "staged sealed backup manifest"
        SidecarPath = Resolve-GoldMFile `
            -Path (Join-Path $resolvedStagingRoot ($manifestName + ".sha256")) `
            -Label "staged sealed backup manifest SHA sidecar"
    }
}

if (-not ($RestoreDatabase -or $RestoreEnvironment -or $RestoreRuntimeSession -or $RestoreEa -or $RestoreTaskAction)) {
    throw "Select at least one restore component"
}
if ($RestoreEnvironment -and -not $RestoreRuntimeSession) {
    throw "RestoreEnvironment requires RestoreRuntimeSession so the EA and worker keep one session identity"
}
if ($Acknowledgement -ne "RESTORE_STOPPED_GOLDM_DATABASE") {
    throw "Restore requires exact acknowledgement: RESTORE_STOPPED_GOLDM_DATABASE"
}

$RepoRoot = Resolve-GoldMDirectory -Path $RepoRoot -Label "repository root"
$maintenanceLock = Enter-GoldMMaintenanceLock `
    -Operation "restore" `
    -RecoveryJournalSha256 $MaintenanceRecoveryJournalSha256
$maintenancePrimaryError = $null
try {
foreach ($binding in @(
    @($PythonExecutable, "PythonExecutable"),
    @($TerminalExecutable, "TerminalExecutable"),
    @($TerminalDataPath, "TerminalDataPath"),
    @($ManifestPath, "ManifestPath")
)) {
    Assert-GoldMAbsolutePathInput -Path ([string]$binding[0]) -Label ([string]$binding[1])
}
if ($EnvFile) { Assert-GoldMAbsolutePathInput -Path $EnvFile -Label "EnvFile" }
if ($DatabasePath) { Assert-GoldMAbsolutePathInput -Path $DatabasePath -Label "DatabasePath" }
$pythonContract = Assert-GoldMPythonInterpreter `
    -PythonExecutable $PythonExecutable `
    -ExpectedSha256 $PythonSha256
$PythonExecutable = $pythonContract.Path
$TerminalExecutable = Resolve-GoldMFile -Path $TerminalExecutable -Label "terminal executable"
$TerminalDataPath = Resolve-GoldMDirectory -Path $TerminalDataPath -Label "terminal data path"
[void](Assert-GoldMStandardTerminalTopology `
    -TerminalExecutable $TerminalExecutable `
    -TerminalDataPath $TerminalDataPath)
if ($ManifestSha256 -notmatch "^[0-9a-fA-F]{64}$") {
    throw "ManifestSha256 must contain exactly 64 hexadecimal characters"
}

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
    -Label "current task-bound runtime environment snapshot"
$DatabasePath = if ($DatabasePath) {
    Resolve-GoldMFile -Path $DatabasePath -Label "current GOLDM database"
}
else {
    Resolve-GoldMFile -Path (Join-Path $runtimeRoot "goldm_signal.db") -Label "current GOLDM database"
}

[void](Assert-GoldMPathWithinDirectory `
    -Path $DatabasePath `
    -Directory $runtimeRoot `
    -Label "DatabasePath")
[void](Protect-GoldMDatabaseArtifacts -DatabasePath $DatabasePath)
$releasesRoot = Resolve-GoldMDirectory `
    -Path (Join-Path $runtimeRoot "releases") `
    -Label "trusted releases root"
Protect-GoldMPrivateFile -Path $EnvFile
Protect-GoldMPrivateFile -Path $DatabasePath

# The operator-supplied directory is never mutated. Copy its complete flat set
# once into a fresh private app-owned leaf, then discard the external authority:
# all parsing, hashing, validation, and restore reads below use only this stage.
$restoreStagingParent = Join-Path $runtimeRoot "restore-staging"
[void](New-GoldMPrivateDirectory -Path $restoreStagingParent)
$restoreStagingRoot = Join-Path $restoreStagingParent (New-GoldMDeploymentNonce)
$staging = Copy-GoldMExternalBackupToPrivateStage `
    -ExternalManifestPath $ManifestPath `
    -StagingRoot $restoreStagingRoot
$ManifestRoot = [string]$staging.Root
$ManifestPath = [string]$staging.ManifestPath
$manifestSidecar = [string]$staging.SidecarPath

$actualManifestSha256 = Get-GoldMFileSha256 -Path $ManifestPath
if (-not $actualManifestSha256.Equals(
    $ManifestSha256,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "Staged backup manifest does not match the operator-supplied SHA-256"
}

[void](Invoke-GoldMDeploymentHelper `
    -PythonExecutable $PythonExecutable `
    -RepoRoot $RepoRoot `
    -Arguments @("verify-seal", "--evidence", $ManifestPath))
$manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$schemaVersionType = $manifest.schemaVersion.GetType().Name
if (
    $schemaVersionType -notin @("Int32", "Int64") -or
    [int]$manifest.schemaVersion -ne 2 -or
    $manifest.purpose -notin @(
    "GOLDM_OPERATOR_BACKUP", "GOLDM_DEPLOY_ROLLBACK"
    )
) {
    throw "Unsupported backup manifest schema/purpose"
}
$expectedManifestName = if ($manifest.purpose -eq "GOLDM_OPERATOR_BACKUP") {
    "backup-manifest.json"
}
else {
    "rollback-manifest.json"
}
if (-not [string]::Equals(
    (Split-Path -Leaf $ManifestPath),
    $expectedManifestName,
    [StringComparison]::Ordinal
)) {
    throw "Backup manifest filename does not match its sealed purpose"
}
if ([string]$manifest.scheduledTask.name -ne $TaskName) {
    throw "Backup manifest belongs to a different Scheduled Task"
}
# Resolve every artifact declared by the sealed manifest before stopping any
# process.  Optional artifacts may be absent, but any non-empty member is still
# required to be a flat, in-directory, non-reparse file with the sealed hash.
$databaseBackup = Resolve-BackupMember -Member ([string]$manifest.database.member)
$envBackup = Resolve-BackupMember -Member ([string]$manifest.environment.member)
$taskXmlBackup = Resolve-BackupMember -Member ([string]$manifest.scheduledTask.xmlMember)
[void](Invoke-GoldMDeploymentHelper `
    -PythonExecutable $PythonExecutable `
    -RepoRoot $RepoRoot `
    -Arguments @(
        "verify-db", "--database", $databaseBackup,
        "--expected-sha256", [string]$manifest.database.sha256
    ))
Assert-BackupHash -Path $envBackup -ExpectedSha256 ([string]$manifest.environment.sha256)
Assert-BackupHash `
    -Path $taskXmlBackup `
    -ExpectedSha256 ([string]$manifest.scheduledTask.xmlSha256)

$needsManifestProofAuthority = (
    $RestoreTaskAction -or $RestoreEa -or $RestoreRuntimeSession
)
$manifestTaskContract = $null
$manifestProofAuthority = $null
if ($needsManifestProofAuthority) {
    # A restored worker/EA/session must be interpreted by the release that
    # produced it.  The current checkout is only the restore orchestrator and
    # cannot redefine an older sealed production-input/session contract.
    $manifestTaskContract = Assert-GoldMWorkerTaskActionContract `
        -Action ([pscustomobject]@{
            Execute = [string]$manifest.scheduledTask.execute
            Arguments = [string]$manifest.scheduledTask.arguments
            WorkingDirectory = [string]$manifest.scheduledTask.workingDirectory
        }) `
        -ExpectedEnvFile $EnvFile `
        -ExpectedDatabasePath $DatabasePath `
        -ReleasesRoot $releasesRoot `
        -HelperPythonExecutable $PythonExecutable `
        -HelperRepoRoot $RepoRoot `
        -RuntimeConfigVerificationFile $envBackup
    if (
        [string]$manifest.workerReleaseCommit -ne [string]$manifestTaskContract.ReleaseCommit -or
        [string]$manifest.workerReleaseTreeManifestSha256 -ne [string]$manifestTaskContract.ReleaseTreeManifestSha256 -or
        [string]$manifest.workerRuntimeConfigSha256 -ne [string]$manifestTaskContract.RuntimeConfigSha256 -or
        [string]$manifest.workerProductionConfigSha256 -ne [string]$manifestTaskContract.ProductionConfigSha256
    ) {
        throw "Backup manifest task release/config binding does not match the sealed release"
    }
    $manifestProofAuthority = Get-GoldMWorkerProofAuthority `
        -TaskActionContract $manifestTaskContract
}

$sessionBackup = ""
if ([string]$manifest.runtimeSession.member) {
    $sessionBackup = Resolve-BackupMember -Member ([string]$manifest.runtimeSession.member)
    Assert-BackupHash -Path $sessionBackup -ExpectedSha256 ([string]$manifest.runtimeSession.sha256)
}
elseif ([bool]$manifest.runtimeSession.exists) {
    throw "Manifest declares a runtime session without a backup member"
}

$eaBackup = ""
if ([string]$manifest.activeEa.mq5Member) {
    $eaBackup = Resolve-BackupMember -Member ([string]$manifest.activeEa.mq5Member)
    Assert-BackupHash -Path $eaBackup -ExpectedSha256 ([string]$manifest.activeEa.mq5Sha256)
}
elseif ([bool]$manifest.activeEa.mq5Exists) {
    throw "Manifest declares an MQ5 artifact without a backup member"
}

$ex5Backup = ""
if ([string]$manifest.activeEa.ex5Member) {
    $ex5Backup = Resolve-BackupMember -Member ([string]$manifest.activeEa.ex5Member)
    Assert-BackupHash -Path $ex5Backup -ExpectedSha256 ([string]$manifest.activeEa.ex5Sha256)
}
elseif ([bool]$manifest.activeEa.ex5Exists) {
    throw "Manifest declares an EX5 artifact without a backup member"
}

$allowedInputFiles = [System.Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
[void](Assert-GoldMReadOnlyFlatDirectory -Path $ManifestRoot)
foreach ($allowedPath in @(
    $ManifestPath,
    $manifestSidecar,
    $databaseBackup,
    $envBackup,
    $taskXmlBackup,
    $sessionBackup,
    $eaBackup,
    $ex5Backup
)) {
    if ($allowedPath) {
        $canonicalAllowedPath = [System.IO.Path]::GetFullPath($allowedPath)
        if (-not $allowedInputFiles.Add($canonicalAllowedPath)) {
            throw "Sealed backup manifest aliases two roles to one member"
        }
    }
}
foreach ($inputFile in @(Get-ChildItem -LiteralPath $ManifestRoot -Force)) {
    if (-not $allowedInputFiles.Contains([System.IO.Path]::GetFullPath($inputFile.FullName))) {
        throw "Private staged backup contains an undeclared entry: $($inputFile.Name)"
    }
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$operatorUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$initialTaskState = [string]$task.State
if ($initialTaskState -notin @("Running", "Ready", "Disabled")) {
    throw "Scheduled Task state is not safe for restore: $initialTaskState"
}
if ($initialTaskState -eq "Disabled") {
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
$currentTaskContract = Assert-GoldMWorkerTaskActionContract `
    -Action (@($task.Actions)[0]) `
    -ExpectedEnvFile $EnvFile `
    -ExpectedDatabasePath $DatabasePath `
    -ReleasesRoot $releasesRoot `
    -HelperPythonExecutable $PythonExecutable `
    -HelperRepoRoot $RepoRoot
$currentProofAuthority = Get-GoldMWorkerProofAuthority `
    -TaskActionContract $currentTaskContract
[void](Invoke-GoldMDeploymentHelper `
    -PythonExecutable ([string]$currentProofAuthority.PythonExecutable) `
    -RepoRoot ([string]$currentProofAuthority.RepoRoot) `
    -Arguments @(
        "validate-env", "--env-file", $EnvFile,
        "--terminal-executable", $TerminalExecutable,
        "--terminal-data-path", $TerminalDataPath
    ))
if (
    $RestoreEnvironment -and
    -not $RestoreTaskAction -and
    -not [string]::Equals(
        [string]$manifest.environment.sha256,
        [string]$currentTaskContract.RuntimeConfigSha256,
        [StringComparison]::Ordinal
    )
) {
    throw "Restored environment digest would break the current worker task binding; restore the sealed task action on its original host or omit RestoreEnvironment"
}
if (
    ($RestoreEa -or $RestoreRuntimeSession) -and
    -not $RestoreTaskAction -and
    -not [string]::Equals(
        [string]$manifestTaskContract.ProductionConfigSha256,
        [string]$currentTaskContract.ProductionConfigSha256,
        [StringComparison]::Ordinal
    )
) {
    throw "Restored EA/session production contract would not match the current worker task; restore the sealed task action on its original host"
}
[void](Disable-GoldMScheduledTaskAndWait -TaskName $TaskName)
[void](Assert-GoldMScheduledTaskControlContract `
    -TaskName $TaskName `
    -ExpectedUserId $operatorUser `
    -RequireDisabled)
$undoManifestPath = ""
$undoManifestSha256 = ""

try {
    # A database rollback cannot safely reconcile an account with any current
    # position or ambiguous broker action.  This gate is repeated after stop.
    [void](Invoke-GoldMDeploymentHelper `
        -PythonExecutable ([string]$currentProofAuthority.PythonExecutable) `
        -RepoRoot ([string]$currentProofAuthority.RepoRoot) `
        -Arguments @(
            "preflight",
            "--env-file", $EnvFile,
            "--database", $DatabasePath,
            "--terminal-executable", $TerminalExecutable,
            "--terminal-data-path", $TerminalDataPath,
            "--release-commit", [string]$currentProofAuthority.ReleaseCommit,
            "--skip-existing-session-evidence"
        ))

    # Create a separately sealed undo point before modifying any component.
    $undoLines = @(& (Join-Path $PSScriptRoot "backup-goldm-windows-vm.ps1") `
        -RepoRoot $RepoRoot `
        -TaskName $TaskName `
        -PythonExecutable $PythonExecutable `
        -PythonSha256 $PythonSha256 `
        -TerminalExecutable $TerminalExecutable `
        -TerminalDataPath $TerminalDataPath `
        -EnvFile $EnvFile `
        -DatabasePath $DatabasePath)
    $undoManifestLine = [string](
        $undoLines | Where-Object { $_ -like "manifest=*" } | Select-Object -Last 1
    )
    $undoManifestShaLine = [string](
        $undoLines |
            Where-Object { $_ -like "manifest_sha256=*" } |
            Select-Object -Last 1
    )
    if (-not $undoManifestLine -or -not $undoManifestShaLine) {
        throw "Pre-restore undo backup returned no authoritative manifest path/digest"
    }
    $undoManifestPath = $undoManifestLine.Substring("manifest=".Length)
    $undoManifestSha256 = $undoManifestShaLine.Substring("manifest_sha256=".Length)
    if (
        -not (Test-Path -LiteralPath $undoManifestPath -PathType Leaf) -or
        $undoManifestSha256 -notmatch "^[0-9a-fA-F]{64}$"
    ) {
        throw "Pre-restore undo backup evidence is invalid"
    }
    $undoActualSha256 = Get-GoldMFileSha256 -Path $undoManifestPath
    if (-not $undoActualSha256.Equals(
        $undoManifestSha256,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Pre-restore undo manifest SHA-256 does not match its emitted authority"
    }
    Write-Output "undo_manifest=$undoManifestPath"
    Write-Output "undo_manifest_sha256=$undoManifestSha256"

    if ($RestoreDatabase) {
        $databaseRestoreAuthority = $currentProofAuthority
        if ($needsManifestProofAuthority) {
            $databaseRestoreAuthority = $manifestProofAuthority
        }
        [void](Invoke-GoldMDeploymentHelper `
            -PythonExecutable ([string]$databaseRestoreAuthority.PythonExecutable) `
            -RepoRoot ([string]$databaseRestoreAuthority.RepoRoot) `
            -Arguments @(
                "inspect-db", "--database", $databaseBackup, "--require-quiescent"
            ))
        [void](Invoke-GoldMDeploymentHelper `
            -PythonExecutable ([string]$databaseRestoreAuthority.PythonExecutable) `
            -RepoRoot ([string]$databaseRestoreAuthority.RepoRoot) `
            -Arguments @(
                "restore-db",
                "--backup", $databaseBackup,
                "--destination", $DatabasePath,
                "--expected-sha256", [string]$manifest.database.sha256,
                "--acknowledgement", $Acknowledgement
            ))
        [void](Protect-GoldMDatabaseArtifacts -DatabasePath $DatabasePath)
    }

    if ($RestoreEnvironment) {
        Assert-BackupHash `
            -Path $envBackup `
            -ExpectedSha256 ([string]$manifest.environment.sha256)
        [void](Invoke-GoldMDeploymentHelper `
            -PythonExecutable ([string]$manifestProofAuthority.PythonExecutable) `
            -RepoRoot ([string]$manifestProofAuthority.RepoRoot) `
            -Arguments @(
                "validate-env", "--env-file", $envBackup,
                "--terminal-executable", $TerminalExecutable,
                "--terminal-data-path", $TerminalDataPath
            ))
        Install-GoldMFileAtomically `
            -Source $envBackup `
            -Destination $EnvFile `
            -ExpectedSha256 ([string]$manifest.environment.sha256)
        Protect-GoldMPrivateFile -Path $EnvFile
    }

    $needsTerminalRestart = $RestoreEa -or $RestoreRuntimeSession
    $cursor = ""
    $logDirectory = Join-Path $TerminalDataPath "MQL5\Logs"
    if ($needsTerminalRestart) {
        $cursor = Join-Path ([System.IO.Path]::GetTempPath()) ("goldm-restore-cursor-" + [guid]::NewGuid().ToString("N") + ".json")
        Stop-GoldMExactTerminalGracefully -TerminalExecutable $TerminalExecutable
        [void](Invoke-GoldMDeploymentHelper `
            -PythonExecutable ([string]$manifestProofAuthority.PythonExecutable) `
            -RepoRoot ([string]$manifestProofAuthority.RepoRoot) `
            -Arguments @(
                "capture-log-cursor", "--log-directory", $logDirectory,
                "--output", $cursor
            ))
    }

    if ($RestoreRuntimeSession) {
        $runtimeSessionTarget = Join-Path $TerminalDataPath "MQL5\Files\goldm_runtime_session.txt"
        if (-not [bool]$manifest.runtimeSession.exists) {
            throw "Manifest has no runtime session file; it cannot activate this fail-closed EA"
        }
        Assert-BackupHash `
            -Path $sessionBackup `
            -ExpectedSha256 ([string]$manifest.runtimeSession.sha256)
        Install-GoldMFileAtomically `
            -Source $sessionBackup `
            -Destination $runtimeSessionTarget `
            -ExpectedSha256 ([string]$manifest.runtimeSession.sha256)
        Protect-GoldMPrivateFile -Path $runtimeSessionTarget
    }

    if ($RestoreEa) {
        if (-not [bool]$manifest.activeEa.mq5Exists -or -not [bool]$manifest.activeEa.ex5Exists) {
            throw "Manifest has no complete MQ5/EX5 pair to restore"
        }
        Assert-BackupHash `
            -Path $eaBackup `
            -ExpectedSha256 ([string]$manifest.activeEa.mq5Sha256)
        Assert-BackupHash `
            -Path $ex5Backup `
            -ExpectedSha256 ([string]$manifest.activeEa.ex5Sha256)
        $restoredMq5 = Join-Path $TerminalDataPath "MQL5\Experts\bot-ea\GoldMSniperParity.mq5"
        $restoredEx5 = Join-Path $TerminalDataPath "MQL5\Experts\bot-ea\GoldMSniperParity.ex5"
        Install-GoldMFileAtomically `
            -Source $eaBackup `
            -Destination $restoredMq5 `
            -ExpectedSha256 ([string]$manifest.activeEa.mq5Sha256)
        Install-GoldMFileAtomically `
            -Source $ex5Backup `
            -Destination $restoredEx5 `
            -ExpectedSha256 ([string]$manifest.activeEa.ex5Sha256)
        Protect-GoldMPrivateFile -Path $restoredMq5
        Protect-GoldMPrivateFile -Path $restoredEx5
    }

    if ($needsTerminalRestart) {
        try {
            Start-GoldMExactTerminal `
                -TerminalExecutable $TerminalExecutable `
                -TerminalDataPath $TerminalDataPath
            [void](Invoke-GoldMDeploymentHelper `
                -PythonExecutable ([string]$manifestProofAuthority.PythonExecutable) `
                -RepoRoot ([string]$manifestProofAuthority.RepoRoot) `
                -Arguments @(
                    "preflight",
                    "--env-file", $EnvFile,
                    "--database", $DatabasePath,
                    "--terminal-executable", $TerminalExecutable,
                    "--terminal-data-path", $TerminalDataPath,
                    "--release-commit", [string]$manifestProofAuthority.ReleaseCommit,
                    "--skip-existing-session-evidence"
                ))
            [void](Wait-GoldMSessionEvidence `
                -PythonExecutable ([string]$manifestProofAuthority.PythonExecutable) `
                -RepoRoot ([string]$manifestProofAuthority.RepoRoot) `
                -LogDirectory $logDirectory `
                -CursorPath $cursor `
                -EnvFile $EnvFile)
        }
        finally {
            if ($cursor -and (Test-Path -LiteralPath $cursor)) {
                Remove-Item -LiteralPath $cursor -Force
            }
        }
    }

    if ($RestoreTaskAction) {
        # Re-verify immediately before registration so a long database/EA
        # restore cannot create a trust/use gap for the old release tree.
        $manifestTaskContract = Assert-GoldMWorkerTaskActionContract `
            -Action ([pscustomobject]@{
                Execute = [string]$manifest.scheduledTask.execute
                Arguments = [string]$manifest.scheduledTask.arguments
                WorkingDirectory = [string]$manifest.scheduledTask.workingDirectory
            }) `
            -ExpectedEnvFile $EnvFile `
            -ExpectedDatabasePath $DatabasePath `
            -ReleasesRoot $releasesRoot `
            -HelperPythonExecutable ([string]$manifestProofAuthority.PythonExecutable) `
            -HelperRepoRoot ([string]$manifestProofAuthority.RepoRoot)
        $restoreExecute = [string]$manifestTaskContract.Execute
        $restoreWorkingDirectory = [string]$manifestTaskContract.WorkingDirectory
        $restoreArguments = [string]$manifestTaskContract.Arguments
        $restoredAction = New-ScheduledTaskAction `
            -Execute $restoreExecute `
            -Argument $restoreArguments `
            -WorkingDirectory $restoreWorkingDirectory
        Set-ScheduledTask -TaskName $TaskName -Action $restoredAction -ErrorAction Stop | Out-Null
        Assert-GoldMScheduledTaskAction `
            -TaskName $TaskName `
            -ExpectedExecute $restoreExecute `
            -ExpectedArguments $restoreArguments `
            -ExpectedWorkingDirectory $restoreWorkingDirectory
        [void](Assert-GoldMScheduledTaskControlContract `
            -TaskName $TaskName `
            -ExpectedUserId $operatorUser `
            -RequireDisabled)
    }

    $finalProofAuthority = $currentProofAuthority
    if ($RestoreTaskAction) {
        $finalProofAuthority = $manifestProofAuthority
    }
    [void](Invoke-GoldMDeploymentHelper `
        -PythonExecutable ([string]$finalProofAuthority.PythonExecutable) `
        -RepoRoot ([string]$finalProofAuthority.RepoRoot) `
        -Arguments @(
            "validate-env", "--env-file", $EnvFile,
            "--terminal-executable", $TerminalExecutable,
            "--terminal-data-path", $TerminalDataPath
        ))
    [void](Invoke-GoldMDeploymentHelper `
        -PythonExecutable ([string]$finalProofAuthority.PythonExecutable) `
        -RepoRoot ([string]$finalProofAuthority.RepoRoot) `
        -Arguments @("inspect-db", "--database", $DatabasePath, "--require-quiescent"))

    if ($StartWorker) {
        $finalTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        if (@($finalTask.Actions).Count -ne 1) {
            throw "Worker task must have exactly one action before readiness start"
        }
        $finalAction = Assert-GoldMWorkerTaskActionContract `
            -Action (@($finalTask.Actions)[0]) `
            -ExpectedEnvFile $EnvFile `
            -ExpectedDatabasePath $DatabasePath `
            -ReleasesRoot $releasesRoot `
            -HelperPythonExecutable ([string]$finalProofAuthority.PythonExecutable) `
            -HelperRepoRoot ([string]$finalProofAuthority.RepoRoot)
        $finalReleaseId = [string]$finalAction.ReleaseCommit
        $finalDeploymentNonceSha256 = [string]$finalAction.DeploymentNonceSha256
        [void](Invoke-GoldMDeploymentHelper `
            -PythonExecutable ([string]$finalProofAuthority.PythonExecutable) `
            -RepoRoot ([string]$finalProofAuthority.RepoRoot) `
            -Arguments @(
                "preflight",
                "--env-file", $EnvFile,
                "--database", $DatabasePath,
                "--terminal-executable", $TerminalExecutable,
                "--terminal-data-path", $TerminalDataPath,
                "--release-commit", $finalReleaseId
            ))
        $readinessNotBeforeUtc = [DateTime]::UtcNow.ToString("o")
        [void](Start-GoldMScheduledTaskAndVerify `
            -TaskName $TaskName `
            -ExpectedExecute ([string]$finalAction.Execute) `
            -ExpectedArguments ([string]$finalAction.Arguments) `
            -ExpectedWorkingDirectory ([string]$finalAction.WorkingDirectory))
        [void](Wait-GoldMTelegramPollReadiness `
            -PythonExecutable ([string]$finalProofAuthority.PythonExecutable) `
            -RepoRoot ([string]$finalProofAuthority.RepoRoot) `
            -DatabasePath $DatabasePath `
            -EnvFile $EnvFile `
            -ExpectedReleaseId $finalReleaseId `
            -ExpectedDeploymentNonceSha256 $finalDeploymentNonceSha256 `
            -ExpectedReleaseManifestSha256 ([string]$finalAction.ReleaseTreeManifestSha256) `
            -ExpectedRuntimeConfigSha256 ([string]$finalAction.RuntimeConfigSha256) `
            -ExpectedProductionConfigSha256 ([string]$finalAction.ProductionConfigSha256) `
            -NotBeforeUtc $readinessNotBeforeUtc)
        [void](Assert-GoldMScheduledTaskRunning `
            -TaskName $TaskName `
            -ExpectedExecute ([string]$finalAction.Execute) `
            -ExpectedArguments ([string]$finalAction.Arguments) `
            -ExpectedWorkingDirectory ([string]$finalAction.WorkingDirectory))
        [void](Invoke-GoldMDeploymentHelper `
            -PythonExecutable ([string]$finalProofAuthority.PythonExecutable) `
            -RepoRoot ([string]$finalProofAuthority.RepoRoot) `
            -Arguments @(
                "preflight",
                "--env-file", $EnvFile,
                "--database", $DatabasePath,
                "--terminal-executable", $TerminalExecutable,
                "--terminal-data-path", $TerminalDataPath,
                "--release-commit", $finalReleaseId
            ))
        [void](Wait-GoldMTelegramPollReadiness `
            -PythonExecutable ([string]$finalProofAuthority.PythonExecutable) `
            -RepoRoot ([string]$finalProofAuthority.RepoRoot) `
            -DatabasePath $DatabasePath `
            -EnvFile $EnvFile `
            -ExpectedReleaseId $finalReleaseId `
            -ExpectedDeploymentNonceSha256 $finalDeploymentNonceSha256 `
            -ExpectedReleaseManifestSha256 ([string]$finalAction.ReleaseTreeManifestSha256) `
            -ExpectedRuntimeConfigSha256 ([string]$finalAction.RuntimeConfigSha256) `
            -ExpectedProductionConfigSha256 ([string]$finalAction.ProductionConfigSha256) `
            -NotBeforeUtc $readinessNotBeforeUtc)
        [void](Assert-GoldMScheduledTaskRunning `
            -TaskName $TaskName `
            -ExpectedExecute ([string]$finalAction.Execute) `
            -ExpectedArguments ([string]$finalAction.Arguments) `
            -ExpectedWorkingDirectory ([string]$finalAction.WorkingDirectory))
        [void](Assert-GoldMScheduledTaskControlContract `
            -TaskName $TaskName `
            -ExpectedUserId $operatorUser `
            -RequireEnabled)
    }
    else {
        Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
        [void](Assert-GoldMScheduledTaskControlContract `
            -TaskName $TaskName `
            -ExpectedUserId $operatorUser `
            -RequireDisabled)
        $finalStoppedAction = $currentTaskContract
        if ($RestoreTaskAction) {
            $finalStoppedAction = $manifestTaskContract
        }
        Assert-GoldMScheduledTaskAction `
            -TaskName $TaskName `
            -ExpectedExecute ([string]$finalStoppedAction.Execute) `
            -ExpectedArguments ([string]$finalStoppedAction.Arguments) `
            -ExpectedWorkingDirectory ([string]$finalStoppedAction.WorkingDirectory)
        # The running-worker branch already sandwiches its final broker proof
        # with fresh readiness plus exact Running/action/control proofs.  This
        # is the corresponding last broker/account/flat-book observation for
        # the default stopped branch.
        [void](Invoke-GoldMDeploymentHelper `
            -PythonExecutable ([string]$finalProofAuthority.PythonExecutable) `
            -RepoRoot ([string]$finalProofAuthority.RepoRoot) `
            -Arguments @(
                "preflight",
                "--env-file", $EnvFile,
                "--database", $DatabasePath,
                "--terminal-executable", $TerminalExecutable,
                "--terminal-data-path", $TerminalDataPath,
                "--release-commit", [string]$finalStoppedAction.ReleaseCommit,
                "--skip-existing-session-evidence"
            ))
        # Re-close the Scheduler/process race after the broker call.  A task
        # enabled or started externally during preflight cannot survive as a
        # false-green stopped restore.
        [void](Disable-GoldMScheduledTaskAndWait -TaskName $TaskName)
        Assert-GoldMScheduledTaskAction `
            -TaskName $TaskName `
            -ExpectedExecute ([string]$finalStoppedAction.Execute) `
            -ExpectedArguments ([string]$finalStoppedAction.Arguments) `
            -ExpectedWorkingDirectory ([string]$finalStoppedAction.WorkingDirectory)
        $finalStoppedTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        if (@($finalStoppedTask.Actions).Count -ne 1) {
            throw "Worker task must have exactly one action after stopped restore"
        }
        $finalStoppedContract = Assert-GoldMWorkerTaskActionContract `
            -Action (@($finalStoppedTask.Actions)[0]) `
            -ExpectedEnvFile $EnvFile `
            -ExpectedDatabasePath $DatabasePath `
            -ReleasesRoot $releasesRoot `
            -HelperPythonExecutable ([string]$finalProofAuthority.PythonExecutable) `
            -HelperRepoRoot ([string]$finalProofAuthority.RepoRoot)
        if (
            -not [string]::Equals(
                [string]$finalStoppedContract.Arguments,
                [string]$finalStoppedAction.Arguments,
                [StringComparison]::Ordinal
            )
        ) {
            throw "Stopped worker task binding changed during final broker proof"
        }
        [void](Assert-GoldMScheduledTaskControlContract `
            -TaskName $TaskName `
            -ExpectedUserId $operatorUser `
            -RequireDisabled)
    }

    [void](Complete-GoldMMaintenanceLock -Lease $maintenanceLock)
    Write-Output "RESTORE_OK"
    Write-Output "worker_state=$((Get-ScheduledTask -TaskName $TaskName).State)"
    Write-Output "undo_manifest=$undoManifestPath"
    Write-Output "undo_manifest_sha256=$undoManifestSha256"
    Write-Output "database_restored=$([bool]$RestoreDatabase)"
    Write-Output "environment_restored=$([bool]$RestoreEnvironment)"
    Write-Output "runtime_session_restored=$([bool]$RestoreRuntimeSession)"
    Write-Output "ea_restored=$([bool]$RestoreEa)"
    Write-Output "task_action_restored=$([bool]$RestoreTaskAction)"
}
catch {
    $restoreError = $_
    try {
        [void](Disable-GoldMScheduledTaskAndWait -TaskName $TaskName)
    }
    catch {
        Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    }
    throw "Restore failed; worker is deliberately stopped. Undo manifest='$undoManifestPath' SHA256='$undoManifestSha256'. Use both values before any further action. Error: $restoreError"
}
}
catch {
    $maintenancePrimaryError = $_
    $journalEvidencePath = ""
    $journalEvidenceSha256 = ""
    if (Get-Variable -Name undoManifestPath -ErrorAction SilentlyContinue) {
        $journalEvidencePath = [string]$undoManifestPath
    }
    if (Get-Variable -Name undoManifestSha256 -ErrorAction SilentlyContinue) {
        $journalEvidenceSha256 = [string]$undoManifestSha256
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
