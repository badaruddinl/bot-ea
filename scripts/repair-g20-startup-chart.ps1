param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('GOLDI', 'GOLDM')]
    [string]$ProfileId,
    [Parameter(Mandatory = $true)]
    [string]$DataPath,
    [Parameter(Mandatory = $true)]
    [string]$TerminalPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,
    [switch]$AcknowledgeProfileRepair
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-AtomicJson {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )
    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $temporary = "$Path.$PID.tmp"
    $Value | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    $stream = [IO.File]::OpenRead($Path)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = $hasher.ComputeHash($stream)
        return ([BitConverter]::ToString($bytes) -replace '-', '').ToLowerInvariant()
    }
    finally {
        $hasher.Dispose()
        $stream.Dispose()
    }
}

if (-not $AcknowledgeProfileRepair) {
    throw 'Explicit -AcknowledgeProfileRepair is required'
}

$resolvedDataPath = [IO.Path]::GetFullPath(
    [Environment]::ExpandEnvironmentVariables($DataPath)
)
$resolvedTerminalPath = [IO.Path]::GetFullPath(
    [Environment]::ExpandEnvironmentVariables($TerminalPath)
)
$resolvedOutputPath = [IO.Path]::GetFullPath(
    [Environment]::ExpandEnvironmentVariables($OutputPath)
)
if (-not (Test-Path -LiteralPath $resolvedDataPath -PathType Container)) {
    throw "MT5 data path is missing: $resolvedDataPath"
}
if (-not (Test-Path -LiteralPath $resolvedTerminalPath -PathType Leaf)) {
    throw "MT5 terminal is missing: $resolvedTerminalPath"
}

$running = @(
    Get-CimInstance Win32_Process -Filter "Name='terminal64.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ExecutablePath -and
            [IO.Path]::GetFullPath([string]$_.ExecutablePath).Equals(
                $resolvedTerminalPath,
                [StringComparison]::OrdinalIgnoreCase
            )
        }
)
if ($running.Count -ne 0) {
    throw "$ProfileId terminal must be stopped before chart-profile repair"
}

$chartRoot = [IO.Path]::GetFullPath(
    (Join-Path $resolvedDataPath 'MQL5\Profiles\Charts\Default')
)
if (-not $chartRoot.StartsWith(
        $resolvedDataPath.TrimEnd('\') + '\',
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw 'Resolved chart profile escaped the configured MT5 data path'
}
$chartPath = Join-Path $chartRoot 'chart01.chr'
$capturedAt = [DateTimeOffset]::UtcNow
$receipt = [ordered]@{
    schema_version = 1
    gate = 'G20'
    profile_id = $ProfileId
    repair_reason = 'STARTUP_CHART_OPEN_FAILED'
    captured_at_utc = $capturedAt.ToString('o')
    production_real_orders = 'DISABLED'
    original_path = $chartPath
    backup_path = $null
    original_sha256 = $null
    original_size_bytes = 0
    result = 'NOOP_CHART_MISSING'
}

if (Test-Path -LiteralPath $chartPath -PathType Leaf) {
    $original = Get-Item -LiteralPath $chartPath
    $originalSize = [long]$original.Length
    $originalHash = Get-Sha256 -Path $chartPath
    $stamp = $capturedAt.ToString('yyyyMMddTHHmmssfffZ')
    $backupPath = "$chartPath.g20-backup-$stamp-$($originalHash.Substring(0, 12))"
    if (Test-Path -LiteralPath $backupPath) {
        throw "Chart backup already exists: $backupPath"
    }
    Move-Item -LiteralPath $chartPath -Destination $backupPath
    if (Test-Path -LiteralPath $chartPath) {
        throw 'Original startup chart still exists after backup move'
    }
    if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
        throw 'Startup chart backup is missing after move'
    }
    $backupHash = Get-Sha256 -Path $backupPath
    if ($backupHash -ne $originalHash) {
        throw 'Startup chart backup hash mismatch'
    }
    $receipt.backup_path = $backupPath
    $receipt.original_sha256 = $originalHash
    $receipt.original_size_bytes = $originalSize
    $receipt.result = 'BACKED_UP_FOR_REGENERATION'
}

Write-AtomicJson -Path $resolvedOutputPath -Value $receipt
$receipt | ConvertTo-Json -Compress -Depth 6
