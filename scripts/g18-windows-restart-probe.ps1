[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Prepare", "Complete")]
    [string]$Mode,

    [Parameter(Mandatory = $true)]
    [string]$StatePath,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [Parameter(Mandatory = $true)]
    [string]$GoldiHeartbeatPath,

    [Parameter(Mandatory = $true)]
    [string]$GoldmHeartbeatPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-AbsolutePath {
    param([Parameter(Mandatory = $true)][string]$Path, [string]$Label)
    if (-not [System.IO.Path]::IsPathFullyQualified($Path)) {
        throw "$Label must be an absolute path"
    }
}

function Get-BootId {
    $operatingSystem = Get-CimInstance -ClassName Win32_OperatingSystem
    return $operatingSystem.LastBootUpTime.ToUniversalTime().ToString("O")
}

function Read-Heartbeat {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][ValidateSet("GOLDI", "GOLDM")][string]$ProfileId
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$ProfileId heartbeat is missing: $Path"
    }
    $heartbeat = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ($heartbeat.profile_id -ne $ProfileId) {
        throw "$ProfileId heartbeat profile mismatch"
    }
    if ([string]$heartbeat.profile_fingerprint -notmatch "^[0-9a-f]{64}$") {
        throw "$ProfileId heartbeat fingerprint is invalid"
    }
    if ($heartbeat.order_authority -ne "DISABLED") {
        throw "$ProfileId heartbeat order authority is unsafe"
    }
    return [ordered]@{
        profile_id = [string]$heartbeat.profile_id
        profile_fingerprint = [string]$heartbeat.profile_fingerprint
        account_login = [long]$heartbeat.account_login
        server = [string]$heartbeat.server
        generation = [long]$heartbeat.generation
        server_time = [long]$heartbeat.server_time
        chart_id = [long]$heartbeat.chart_id
        last_write_utc = (Get-Item -LiteralPath $Path).LastWriteTimeUtc.ToString("O")
        order_authority = "DISABLED"
    }
}

function Write-JsonAtomic {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)]$Value)
    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $temporary = "$Path.tmp"
    $json = $Value | ConvertTo-Json -Depth 12
    [System.IO.File]::WriteAllText(
        $temporary,
        $json + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

foreach ($item in @(
    @($StatePath, "StatePath"),
    @($OutputPath, "OutputPath"),
    @($GoldiHeartbeatPath, "GoldiHeartbeatPath"),
    @($GoldmHeartbeatPath, "GoldmHeartbeatPath")
)) {
    Assert-AbsolutePath -Path $item[0] -Label $item[1]
}

$bootId = Get-BootId
$goldi = Read-Heartbeat -Path $GoldiHeartbeatPath -ProfileId "GOLDI"
$goldm = Read-Heartbeat -Path $GoldmHeartbeatPath -ProfileId "GOLDM"

if ($Mode -eq "Prepare") {
    $state = [ordered]@{
        schema_version = 1
        status = "PENDING_REBOOT"
        probe_id = [guid]::NewGuid().ToString("D")
        prepared_at_utc = [DateTimeOffset]::UtcNow.ToString("O")
        prepared_boot_id = $bootId
        profiles = [ordered]@{ GOLDI = $goldi; GOLDM = $goldm }
        production_real_orders = "DISABLED"
    }
    Write-JsonAtomic -Path $StatePath -Value $state
    Write-Output "G18_REBOOT_PROBE_PREPARED state=$StatePath"
    exit 0
}

if (-not (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
    throw "prepared restart state is missing: $StatePath"
}
$prepared = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
if ($prepared.status -ne "PENDING_REBOOT") {
    throw "restart state is not pending"
}
if ($prepared.production_real_orders -ne "DISABLED") {
    throw "prepared restart state has unsafe authority"
}
$currentBootTime = [DateTimeOffset]::Parse($bootId).ToUniversalTime()
$preparedBootTime = ([DateTimeOffset]$prepared.prepared_boot_id).ToUniversalTime()
if ($currentBootTime -eq $preparedBootTime) {
    throw "Windows/VM boot ID did not change"
}
$bootTime = $currentBootTime
foreach ($profile in @($goldi, $goldm)) {
    if ([DateTimeOffset]::Parse($profile.last_write_utc) -le $bootTime) {
        throw "$($profile.profile_id) heartbeat was not written after reboot"
    }
    $before = $prepared.profiles.($profile.profile_id)
    if ($profile.profile_fingerprint -ne [string]$before.profile_fingerprint) {
        throw "$($profile.profile_id) fingerprint changed across reboot"
    }
    if ($profile.account_login -ne [long]$before.account_login -or
        $profile.server -ne [string]$before.server) {
        throw "$($profile.profile_id) binding changed across reboot"
    }
    if ($profile.chart_id -eq [long]$before.chart_id) {
        throw "$($profile.profile_id) process identity did not change across reboot"
    }
}

$report = [ordered]@{
    schema_version = 1
    result = "PASS"
    proof = "windows_restart"
    probe_id = [string]$prepared.probe_id
    prepared_boot_id = $preparedBootTime.ToString("O")
    completed_boot_id = $bootId
    boot_id_changed = $true
    both_profiles_recovered = $true
    goldi_identity_changed = $true
    goldm_identity_changed = $true
    profiles = [ordered]@{ GOLDI = $goldi; GOLDM = $goldm }
    production_real_orders = "DISABLED"
}
Write-JsonAtomic -Path $OutputPath -Value $report
$digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $OutputPath).Hash.ToLowerInvariant()
$checksumPath = [System.IO.Path]::ChangeExtension($OutputPath, ".sha256")
[System.IO.File]::WriteAllText(
    $checksumPath,
    "$digest  $([System.IO.Path]::GetFileName($OutputPath))`n",
    [System.Text.Encoding]::ASCII
)
Write-Output "G18_REBOOT_PROBE_PASS output=$OutputPath"
