[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [Parameter(Mandatory = $true)][string]$GoldiTerminalPath,
    [Parameter(Mandatory = $true)][string]$GoldmTerminalPath,
    [Parameter(Mandatory = $true)][int]$BridgeProcessId,
    [Parameter(Mandatory = $true)][string]$GoldiHeartbeatPath,
    [Parameter(Mandatory = $true)][string]$GoldmHeartbeatPath,
    [Parameter(Mandatory = $true)][string]$DatabasePath,
    [Parameter(Mandatory = $true)][string]$GoldiSpoolPath,
    [Parameter(Mandatory = $true)][string]$GoldmSpoolPath,
    [Parameter(Mandatory = $true)][string]$LatencyPath,
    [ValidateSet("ProfileFile", "ProcessCpu")][string]$LivenessMode = "ProfileFile",
    [ValidateRange(12, 86400)][int]$SampleCount = 120,
    [ValidateRange(1, 3600)][int]$IntervalSeconds = 5
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-AbsolutePath {
    param([Parameter(Mandatory = $true)][string]$Path, [string]$Label)
    if (-not [System.IO.Path]::IsPathRooted($Path)) {
        throw "$Label must be an absolute path"
    }
}

function Get-FileLength {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return 0L
    }
    return [long](Get-Item -LiteralPath $Path).Length
}

function Get-SpoolEventCount {
    param([Parameter(Mandatory = $true)][string[]]$Paths)
    [long]$count = 0
    foreach ($path in $Paths) {
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $count += @(
                Get-Content -LiteralPath $path |
                    Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
            ).Count
        }
    }
    return $count
}

function Resolve-ExactProcess {
    param(
        [Parameter(Mandatory = $true)][string]$ExecutablePath,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $matches = @(
        Get-Process -Name "terminal64" -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -eq $ExecutablePath }
    )
    if ($matches.Count -ne 1) {
        throw "$Label requires exactly one terminal process; found $($matches.Count)"
    }
    return $matches[0]
}

function Read-HeartbeatGeneration {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ProfileId
    )
    $heartbeat = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ($heartbeat.profile_id -ne $ProfileId -or
        $heartbeat.order_authority -ne "DISABLED") {
        throw "$ProfileId heartbeat is invalid or unsafe"
    }
    return [long]$heartbeat.generation
}

function Get-LivenessGeneration {
    param(
        [Parameter(Mandatory = $true)]$Process,
        [Parameter(Mandatory = $true)][string]$HeartbeatPath,
        [Parameter(Mandatory = $true)][string]$ProfileId,
        [Parameter(Mandatory = $true)][string]$Mode
    )
    if ($Mode -eq "ProfileFile") {
        return Read-HeartbeatGeneration -Path $HeartbeatPath -ProfileId $ProfileId
    }
    $Process.Refresh()
    return [long]([Math]::Floor([double]$Process.CPU * 1000.0))
}

function Get-ProcessMetrics {
    param(
        [Parameter(Mandatory = $true)]$Process,
        [long]$HeartbeatGeneration = -1
    )
    $Process.Refresh()
    $value = [ordered]@{
        process_id = [int]$Process.Id
        rss_bytes = [long]$Process.WorkingSet64
        private_bytes = [long]$Process.PrivateMemorySize64
        cpu_seconds = [double]$Process.CPU
        handle_count = [int]$Process.HandleCount
        thread_count = [int]$Process.Threads.Count
    }
    if ($HeartbeatGeneration -ge 0) {
        $value.heartbeat_generation = $HeartbeatGeneration
    }
    return $value
}

foreach ($item in @(
    @($OutputPath, "OutputPath"),
    @($GoldiTerminalPath, "GoldiTerminalPath"),
    @($GoldmTerminalPath, "GoldmTerminalPath"),
    @($GoldiHeartbeatPath, "GoldiHeartbeatPath"),
    @($GoldmHeartbeatPath, "GoldmHeartbeatPath"),
    @($DatabasePath, "DatabasePath"),
    @($GoldiSpoolPath, "GoldiSpoolPath"),
    @($GoldmSpoolPath, "GoldmSpoolPath"),
    @($LatencyPath, "LatencyPath")
)) {
    Assert-AbsolutePath -Path $item[0] -Label $item[1]
}
if (-not (Test-Path -LiteralPath $LatencyPath -PathType Leaf)) {
    throw "LatencyPath is missing"
}

$goldi = Resolve-ExactProcess -ExecutablePath $GoldiTerminalPath -Label "GOLDI"
$goldm = Resolve-ExactProcess -ExecutablePath $GoldmTerminalPath -Label "GOLDM"
$bridge = Get-Process -Id $BridgeProcessId -ErrorAction Stop
$samples = [System.Collections.Generic.List[object]]::new()

for ($index = 0; $index -lt $SampleCount; $index++) {
    if ($goldi.HasExited -or $goldm.HasExited -or $bridge.HasExited) {
        throw "A measured component exited during capture"
    }
    $samples.Add([ordered]@{
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString("O")
        components = [ordered]@{
            GOLDI = Get-ProcessMetrics -Process $goldi -HeartbeatGeneration (
                Get-LivenessGeneration -Process $goldi -HeartbeatPath $GoldiHeartbeatPath `
                    -ProfileId "GOLDI" -Mode $LivenessMode
            )
            GOLDM = Get-ProcessMetrics -Process $goldm -HeartbeatGeneration (
                Get-LivenessGeneration -Process $goldm -HeartbeatPath $GoldmHeartbeatPath `
                    -ProfileId "GOLDM" -Mode $LivenessMode
            )
            BRIDGE = Get-ProcessMetrics -Process $bridge
        }
        storage = [ordered]@{
            event_count = Get-SpoolEventCount -Paths @($GoldiSpoolPath, $GoldmSpoolPath)
            database_bytes = Get-FileLength -Path $DatabasePath
            wal_bytes = Get-FileLength -Path "$DatabasePath-wal"
            goldi_spool_bytes = Get-FileLength -Path $GoldiSpoolPath
            goldm_spool_bytes = Get-FileLength -Path $GoldmSpoolPath
        }
    })
    if ($index + 1 -lt $SampleCount) {
        Start-Sleep -Seconds $IntervalSeconds
    }
}

$latencies = Get-Content -LiteralPath $LatencyPath -Raw | ConvertFrom-Json
$report = [ordered]@{
    schema_version = 1
    captured_at_utc = [DateTimeOffset]::UtcNow.ToString("O")
    interval_seconds = $IntervalSeconds
    samples = $samples
    latencies_ms = $latencies
    production_real_orders = "DISABLED"
}
$directory = Split-Path -Parent $OutputPath
if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}
$temporary = "$OutputPath.tmp"
$report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temporary -Encoding UTF8
Move-Item -LiteralPath $temporary -Destination $OutputPath -Force
Write-Output "G19_RESOURCE_CAPTURE_COMPLETE samples=$SampleCount output=$OutputPath"
