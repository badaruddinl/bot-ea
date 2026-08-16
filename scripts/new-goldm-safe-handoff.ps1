param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [Parameter(Mandatory = $true)][string]$PythonExecutable,
    [Parameter(Mandatory = $true)][string]$PythonSha256,
    [Parameter(Mandatory = $true)][string]$TerminalExecutable,
    [Parameter(Mandatory = $true)][string]$TerminalDataPath,
    [Parameter(Mandatory = $true)][string]$ApprovedBy,
    [Parameter(Mandatory = $true)][string]$Reason,
    [Parameter(Mandatory = $true)][string]$Acknowledgement,
    [string]$ReleaseCommit = "HEAD",
    [string]$EnvFile = "",
    [string]$DatabasePath = "",
    [int]$ValidityMinutes = 10,
    [string]$MaintenanceRecoveryJournalSha256 = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot "goldm-deployment-common.psm1") -Force

if ($Acknowledgement -ne "I_ACCEPT_PROTECTED_POSITION_HANDOFF") {
    throw "Use the exact acknowledgement I_ACCEPT_PROTECTED_POSITION_HANDOFF after verifying every position has broker SL and TP"
}
$RepoRoot = Resolve-GoldMDirectory -Path $RepoRoot -Label "repository root"
$maintenanceLock = Enter-GoldMMaintenanceLock `
    -Operation "handoff" `
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
$pythonContract = Assert-GoldMPythonInterpreter `
    -PythonExecutable $PythonExecutable `
    -ExpectedSha256 $PythonSha256
$PythonExecutable = $pythonContract.Path
$TerminalExecutable = Resolve-GoldMFile -Path $TerminalExecutable -Label "terminal executable"
$TerminalDataPath = Resolve-GoldMDirectory -Path $TerminalDataPath -Label "terminal data path"
[void](Assert-GoldMStandardTerminalTopology `
    -TerminalExecutable $TerminalExecutable `
    -TerminalDataPath $TerminalDataPath)
$EnvFile = if ($EnvFile) {
    Resolve-GoldMFile -Path $EnvFile -Label "environment file"
}
else {
    Resolve-GoldMFile -Path (Join-Path $RepoRoot ".env") -Label "environment file"
}
$DatabasePath = if ($DatabasePath) {
    Resolve-GoldMFile -Path $DatabasePath -Label "GOLDM database"
}
else {
    Resolve-GoldMFile -Path (Join-Path $RepoRoot "runtime_data\goldm_signal.db") -Label "GOLDM database"
}

$runtimeRoot = Join-Path $RepoRoot "runtime_data"
[void](Assert-GoldMPathWithinDirectory `
    -Path $DatabasePath `
    -Directory $runtimeRoot `
    -Label "DatabasePath")
New-GoldMPrivateDirectory -Path $runtimeRoot
[void](Protect-GoldMDatabaseArtifacts -DatabasePath $DatabasePath)
Protect-GoldMPrivateFile -Path $EnvFile
Protect-GoldMPrivateFile -Path $DatabasePath

if ($ReleaseCommit -ne "HEAD" -and $ReleaseCommit -notmatch "^[0-9a-f]{40}$") {
    throw "ReleaseCommit must be HEAD or one full lowercase 40-hex commit SHA"
}
$commit = (& git -C $RepoRoot rev-parse ($ReleaseCommit + "^{commit}")).Trim()
if ($LASTEXITCODE -ne 0 -or $commit -notmatch "^[0-9a-f]{40}$") {
    throw "ReleaseCommit did not resolve to an immutable commit"
}
$handoffRoot = Join-Path $RepoRoot "runtime_data\handoffs"
New-GoldMPrivateDirectory -Path $handoffRoot
$output = Join-Path $handoffRoot (
    "handoff-" + [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ") + "-" +
    [guid]::NewGuid().ToString("N").Substring(0, 8) + ".json"
)
$result = Invoke-GoldMDeploymentHelper `
    -PythonExecutable $PythonExecutable `
    -RepoRoot $RepoRoot `
    -Arguments @(
        "create-handoff",
        "--env-file", $EnvFile,
        "--database", $DatabasePath,
        "--terminal-executable", $TerminalExecutable,
        "--terminal-data-path", $TerminalDataPath,
        "--release-commit", $commit,
        "--approved-by", $ApprovedBy,
        "--reason", $Reason,
        "--output", $output,
        "--acknowledgement", $Acknowledgement,
        "--validity-minutes", [string]$ValidityMinutes
    )
Protect-GoldMPrivateFile -Path ([string]$result.path)
Protect-GoldMPrivateFile -Path (([string]$result.path) + ".sha256")

[void](Complete-GoldMMaintenanceLock -Lease $maintenanceLock)
Write-Output "SAFE_HANDOFF_CREATED"
Write-Output "manifest=$($result.path)"
Write-Output "sha256=$($result.sha256)"
Write-Output "expires_at_utc=$($result.expires_at_utc)"
Write-Output "position_count=$($result.position_count)"
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
