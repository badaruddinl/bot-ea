param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-ConfiguredPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [Environment]::ExpandEnvironmentVariables($Path)
}

function Get-ExactProcess {
    param([Parameter(Mandatory = $true)][string]$ExecutablePath)
    $expected = [IO.Path]::GetFullPath($ExecutablePath)
    return @(
        Get-CimInstance Win32_Process -Filter "Name='terminal64.exe'" -ErrorAction SilentlyContinue |
            Where-Object {
                $_.ExecutablePath -and
                [IO.Path]::GetFullPath([string]$_.ExecutablePath).Equals(
                    $expected,
                    [StringComparison]::OrdinalIgnoreCase
                )
            }
    )
}

function Get-PortableProcessId {
    param($Process)
    if ($null -eq $Process) {
        return $null
    }
    if ($null -ne $Process.PSObject.Properties['ProcessId']) {
        return [int]$Process.ProcessId
    }
    if ($null -ne $Process.PSObject.Properties['Id']) {
        return [int]$Process.Id
    }
    return $null
}

function Assert-FileHash {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label is missing: $Path"
    }
    if ($ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        throw "$Label expected_sha256 must contain exactly 64 hexadecimal characters"
    }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    if (-not $actual.Equals($ExpectedSha256, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label hash mismatch"
    }
}

function Read-G20Config {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "G20 config is missing: $Path"
    }
    $value = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ([int]$value.schema_version -ne 1) {
        throw "Unsupported G20 config schema_version"
    }
    if ([string]$value.production_real_orders -ne "DISABLED") {
        throw "G20 requires production_real_orders=DISABLED"
    }
    if ([string]$value.startup_mode -notin @(
            'PASSWORD_AT_STARTUP',
            'AUTOLOGON_LOCKED_INTERACTIVE'
        )) {
        throw "Unsupported G20 startup_mode"
    }
    if ([double]$value.poll_seconds -lt 1.0) {
        throw "poll_seconds must be at least one second"
    }
    if (@($value.terminals).Count -ne 2) {
        throw "Exactly two terminal profiles are required"
    }
    $ids = @($value.terminals | ForEach-Object { [string]$_.profile_id })
    if (($ids | Sort-Object) -join ',' -ne 'GOLDI,GOLDM') {
        throw "Terminal profiles must be exactly GOLDI and GOLDM"
    }
    $terminalPaths = @(
        $value.terminals | ForEach-Object {
            [IO.Path]::GetFullPath((Resolve-ConfiguredPath ([string]$_.terminal_path))).ToLowerInvariant()
        }
    )
    if (($terminalPaths | Select-Object -Unique).Count -ne 2) {
        throw "GOLDI and GOLDM must use distinct terminal installations"
    }
    foreach ($terminal in @($value.terminals)) {
        $terminalPath = Resolve-ConfiguredPath ([string]$terminal.terminal_path)
        $eaPath = Resolve-ConfiguredPath ([string]$terminal.ea_binary_path)
        if (-not (Test-Path -LiteralPath $terminalPath -PathType Leaf)) {
            throw "$($terminal.profile_id) terminal is missing: $terminalPath"
        }
        Assert-FileHash -Path $eaPath -ExpectedSha256 ([string]$terminal.ea_sha256) `
            -Label "$($terminal.profile_id) EA"
        if ([long]$terminal.expected_account_login -le 0) {
            throw "$($terminal.profile_id) expected_account_login must be positive"
        }
        if ([string]::IsNullOrWhiteSpace([string]$terminal.expected_account_server)) {
            throw "$($terminal.profile_id) expected_account_server is required"
        }
        if ([string]$terminal.expected_profile_fingerprint -notmatch '^[0-9a-fA-F]{64}$') {
            throw "$($terminal.profile_id) expected_profile_fingerprint is invalid"
        }
        if ([int]$terminal.expected_trade_mode -notin @(0, 2)) {
            throw "$($terminal.profile_id) expected_trade_mode must be DEMO(0) or REAL(2)"
        }
        if ([string]$terminal.expected_order_authority -notin @('ENABLED', 'DISABLED')) {
            throw "$($terminal.profile_id) expected_order_authority is invalid"
        }
        if ($terminal.profile_id -eq 'GOLDM' -and $terminal.expected_order_authority -ne 'DISABLED') {
            throw "GOLDM REAL order authority must remain DISABLED"
        }
        if (
            ($terminal.profile_id -eq 'GOLDI' -and $terminal.expected_symbol -ne 'GOLD.i#') -or
            ($terminal.profile_id -eq 'GOLDM' -and $terminal.expected_symbol -ne 'GOLDm#')
        ) {
            throw "$($terminal.profile_id) expected_symbol does not match its locked profile"
        }
        $spoolPath = Resolve-ConfiguredPath ([string]$terminal.spool_path)
        if ([string]::IsNullOrWhiteSpace($spoolPath)) {
            throw "$($terminal.profile_id) spool_path is required"
        }
        if ([string]$terminal.arguments -match '(?i)(password|/login:|--login)') {
            throw "$($terminal.profile_id) arguments may not contain credentials"
        }
    }
    if ([bool]$value.bridge.enabled) {
        $secretPath = Resolve-ConfiguredPath ([string]$value.bridge.token_secret_path)
        if (-not (Test-Path -LiteralPath $secretPath -PathType Leaf)) {
            throw "Bridge DPAPI token secret is missing: $secretPath"
        }
        $adminIds = @($value.bridge.admin_chat_ids)
        if ($adminIds.Count -eq 0 -or
            @($adminIds | Where-Object { [string]$_ -notmatch '^-?[1-9][0-9]*$' }).Count -gt 0) {
            throw "Bridge administrator chat IDs are invalid"
        }
    }
    return $value
}

function Start-BridgeProcess {
    param(
        [Parameter(Mandatory = $true)]$Bridge,
        [Parameter(Mandatory = $true)][string]$ExecutablePath,
        [Parameter(Mandatory = $true)][string]$Arguments
    )
    $secretPath = Resolve-ConfiguredPath ([string]$Bridge.token_secret_path)
    $encrypted = (Get-Content -LiteralPath $secretPath -Raw).Trim()
    $secure = $encrypted | ConvertTo-SecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    $previousToken = $env:TELEGRAM_BOT_TOKEN
    $previousAdmins = $env:TELEGRAM_ADMIN_CHAT_IDS
    try {
        $env:TELEGRAM_BOT_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        $env:TELEGRAM_ADMIN_CHAT_IDS = @($Bridge.admin_chat_ids) -join ','
        return Start-Process -FilePath $ExecutablePath -ArgumentList $Arguments `
            -WindowStyle Hidden -PassThru
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        $secure.Dispose()
        $env:TELEGRAM_BOT_TOKEN = $previousToken
        $env:TELEGRAM_ADMIN_CHAT_IDS = $previousAdmins
    }
}

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
    $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Ensure-ParentDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)
    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
}

$resolvedConfig = [IO.Path]::GetFullPath((Resolve-ConfiguredPath $ConfigPath))
$config = Read-G20Config -Path $resolvedConfig
$healthPath = Resolve-ConfiguredPath ([string]$config.health_path)
$auditPath = Resolve-ConfiguredPath ([string]$config.audit_path)
Ensure-ParentDirectory -Path $healthPath
Ensure-ParentDirectory -Path $auditPath

if ($ValidateOnly) {
    [ordered]@{
        schema_version = 1
        status = "VALID"
        config_path = $resolvedConfig
        profiles = @($config.terminals | ForEach-Object { [string]$_.profile_id })
        production_real_orders = "DISABLED"
    } | ConvertTo-Json -Compress
    exit 0
}

$startedAt = [DateTimeOffset]::UtcNow
$restartCounts = @{ GOLDI = 0; GOLDM = 0; BRIDGE = 0 }
$bridgeProcess = $null

while ($true) {
    $profileHealth = @()
    foreach ($terminal in @($config.terminals)) {
        $profileId = [string]$terminal.profile_id
        $terminalPath = Resolve-ConfiguredPath ([string]$terminal.terminal_path)
        $eaPath = Resolve-ConfiguredPath ([string]$terminal.ea_binary_path)
        $state = "RUNNING"
        $failure = $null
        $process = $null
        try {
            Assert-FileHash -Path $eaPath -ExpectedSha256 ([string]$terminal.ea_sha256) `
                -Label "$profileId EA"
            $matches = @(Get-ExactProcess -ExecutablePath $terminalPath)
            if ($matches.Count -gt 1) {
                throw "$profileId has duplicate terminal processes"
            }
            if ($matches.Count -eq 0) {
                $arguments = [string]$terminal.arguments
                if ([string]::IsNullOrWhiteSpace($arguments)) {
                    $process = Start-Process -FilePath $terminalPath -WindowStyle Hidden -PassThru
                }
                else {
                    $process = Start-Process -FilePath $terminalPath -ArgumentList $arguments `
                        -WindowStyle Hidden -PassThru
                }
                $restartCounts[$profileId] = [int]$restartCounts[$profileId] + 1
                Start-Sleep -Seconds 2
            }
            else {
                $process = $matches[0]
            }
        }
        catch {
            $state = "FAILED_CLOSED"
            $failure = $_.Exception.Message
        }
        $profileHealth += [ordered]@{
            profile_id = $profileId
            state = $state
            pid = Get-PortableProcessId -Process $process
            terminal_path = $terminalPath
            ea_sha256 = ([string]$terminal.ea_sha256).ToLowerInvariant()
            expected_account_login = [long]$terminal.expected_account_login
            expected_account_server = [string]$terminal.expected_account_server
            expected_profile_fingerprint = ([string]$terminal.expected_profile_fingerprint).ToLowerInvariant()
            expected_symbol = [string]$terminal.expected_symbol
            expected_trade_mode = [int]$terminal.expected_trade_mode
            expected_order_authority = [string]$terminal.expected_order_authority
            restart_count = [int]$restartCounts[$profileId]
            failure = $failure
        }
    }

    $bridgeHealth = [ordered]@{ enabled = [bool]$config.bridge.enabled; state = "DISABLED"; pid = $null }
    if ([bool]$config.bridge.enabled) {
        try {
            $bridgeExe = Resolve-ConfiguredPath ([string]$config.bridge.executable_path)
            if (-not (Test-Path -LiteralPath $bridgeExe -PathType Leaf)) {
                throw "Bridge executable is missing: $bridgeExe"
            }
            if ($null -eq $bridgeProcess -or $bridgeProcess.HasExited) {
                $bridgeArguments = [string]$config.bridge.arguments
                if ($bridgeArguments -match '(?i)(bot[_-]?token|password|AA[A-Za-z0-9_-]{20,})') {
                    throw "Bridge arguments may not contain credentials"
                }
                $bridgeProcess = Start-BridgeProcess -Bridge $config.bridge `
                    -ExecutablePath $bridgeExe -Arguments $bridgeArguments
                $restartCounts.BRIDGE = [int]$restartCounts.BRIDGE + 1
            }
            $bridgeHealth.state = "RUNNING"
            $bridgeHealth.pid = [int]$bridgeProcess.Id
        }
        catch {
            $bridgeHealth.state = "FAILED"
            $bridgeHealth.failure = $_.Exception.Message
        }
    }

    $health = [ordered]@{
        schema_version = 1
        supervisor_pid = $PID
        started_at_utc = $startedAt.ToString('o')
        observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        windows_identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        interactive_session = [Environment]::UserInteractive
        session_id = [Diagnostics.Process]::GetCurrentProcess().SessionId
        startup_mode = [string]$config.startup_mode
        production_real_orders = "DISABLED"
        terminals = $profileHealth
        bridge = $bridgeHealth
    }
    Write-AtomicJson -Path $healthPath -Value $health
    $health | ConvertTo-Json -Compress -Depth 8 | Add-Content -LiteralPath $auditPath -Encoding UTF8
    Start-Sleep -Seconds ([double]$config.poll_seconds)
}
