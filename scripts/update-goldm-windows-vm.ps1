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
    [string]$Remote = "origin",
    [string]$RemoteBranch = "release/goldm-core-v2",
    [Parameter(Mandatory = $true)][string]$ExpectedCommit,
    [string]$EnvFile = "",
    [string]$DatabasePath = "",
    [string]$SafeHandoffManifest = "",
    [string]$SafeHandoffSha256 = "",
    [string]$MaintenanceRecoveryJournalSha256 = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot "goldm-deployment-common.psm1") -Force

$RepoRoot = Resolve-GoldMDirectory -Path $RepoRoot -Label "repository root"
$maintenanceLock = Enter-GoldMMaintenanceLock `
    -Operation "update" `
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
$pythonContract = Assert-GoldMPythonInterpreter `
    -PythonExecutable $PythonExecutable `
    -ExpectedSha256 $PythonSha256
$PythonExecutable = [string]$pythonContract.Path
$TerminalExecutable = Resolve-GoldMFile -Path $TerminalExecutable -Label "terminal executable"
$TerminalDataPath = Resolve-GoldMDirectory -Path $TerminalDataPath -Label "terminal data path"
[void](Assert-GoldMStandardTerminalTopology `
    -TerminalExecutable $TerminalExecutable `
    -TerminalDataPath $TerminalDataPath)
$MetaEditorPath = Assert-GoldMMetaEditorExecutable -MetaEditorPath $MetaEditorPath
$WheelhousePath = Resolve-GoldMDirectory -Path $WheelhousePath -Label "sealed offline wheelhouse"
if ($WheelhouseManifestSha256 -notmatch "^[0-9a-fA-F]{64}$") {
    throw "WheelhouseManifestSha256 must contain exactly 64 hexadecimal characters"
}
if (
    $Remote -notmatch "^[A-Za-z0-9][A-Za-z0-9._-]*$" -or
    $RemoteBranch -notmatch "^[A-Za-z0-9][A-Za-z0-9._/-]*$" -or
    $RemoteBranch.Contains("..") -or
    $RemoteBranch.Contains("//") -or
    $RemoteBranch.Contains("@{") -or
    $RemoteBranch.EndsWith("/") -or
    $RemoteBranch.EndsWith(".") -or
    $RemoteBranch.EndsWith(".lock", [StringComparison]::OrdinalIgnoreCase)
) {
    throw "Remote/branch contains unsupported characters"
}
if ($ExpectedCommit -notmatch "^[0-9a-f]{40}$") {
    throw "ExpectedCommit must be one operator-reviewed full lowercase 40-hex SHA"
}

# Fetch updates only Git object/ref metadata.  It never checks out or pulls into
# the working directory used by a legacy worker.  deploy builds a separate
# release/venv and verifies it before stopping the current task.
Set-Location -LiteralPath $RepoRoot
Invoke-GoldMNativeChecked "git_fetch_release_ref" {
    & git fetch --no-tags --prune $Remote $RemoteBranch
}
$resolved = (& git rev-parse "FETCH_HEAD^{commit}").Trim()
if ($LASTEXITCODE -ne 0 -or $resolved -notmatch "^[0-9a-f]{40}$") {
    throw "FETCH_HEAD from the requested remote branch did not resolve to an immutable commit"
}
if ($resolved -cne $ExpectedCommit) {
    throw "FETCH_HEAD does not equal the operator-reviewed ExpectedCommit"
}

$arguments = @{
    RepoRoot = $RepoRoot
    TaskName = $TaskName
    PythonExecutable = $PythonExecutable
    PythonSha256 = $PythonSha256
    TerminalExecutable = $TerminalExecutable
    TerminalDataPath = $TerminalDataPath
    MetaEditorPath = $MetaEditorPath
    WheelhousePath = $WheelhousePath
    WheelhouseManifestSha256 = $WheelhouseManifestSha256
    ReleaseCommit = $resolved
}
if ($EnvFile) { $arguments.EnvFile = $EnvFile }
if ($DatabasePath) { $arguments.DatabasePath = $DatabasePath }
if ($SafeHandoffManifest) { $arguments.SafeHandoffManifest = $SafeHandoffManifest }
if ($SafeHandoffSha256) { $arguments.SafeHandoffSha256 = $SafeHandoffSha256 }

& (Join-Path $PSScriptRoot "deploy-goldm-windows-vm.ps1") @arguments
if (-not $?) { throw "Deployment of fetched release failed" }
[void](Complete-GoldMMaintenanceLock -Lease $maintenanceLock)
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
