param(
    [Parameter(Mandatory = $true)]
    [string]$GoldiDataPath,
    [Parameter(Mandatory = $true)]
    [string]$GoldmDataPath,
    [string]$OutputRoot = "C:\bot-ea-g20",
    [bool]$BridgeEnabled = $true,
    [string]$PythonwPath = "",
    [string]$TelegramSecretPath = "$env:ProgramData\bot-ea\g20\telegram-token.dpapi",
    [string[]]$TelegramAdminChatIds = @(),
    [ValidateSet('PASSWORD_AT_STARTUP', 'AUTOLOGON_LOCKED_INTERACTIVE')]
    [string]$StartupMode = 'PASSWORD_AT_STARTUP'
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$goldiTerminal = "C:\Program Files\MetaTrader 5\terminal64.exe"
$goldmTerminal = "C:\Program Files\MetaTrader 5 GOLDm\terminal64.exe"
$goldiSource = Join-Path $repoRoot "mt5\Experts\bot-ea\GoldEngine-GOLDi.ex5"
$goldmSource = Join-Path $repoRoot "mt5\Experts\bot-ea\GoldEngine-GOLDm.ex5"

foreach ($path in @($goldiTerminal, $goldmTerminal, $goldiSource, $goldmSource)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required G20 file is missing: $path"
    }
}
foreach ($path in @($GoldiDataPath, $GoldmDataPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        throw "MT5 data path is missing: $path"
    }
}
if ([IO.Path]::GetFullPath($GoldiDataPath).Equals(
        [IO.Path]::GetFullPath($GoldmDataPath),
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw "GOLDI and GOLDM data paths must be distinct"
}

$bindings = @(
    [ordered]@{
        profile_id = "GOLDI"
        data_path = [IO.Path]::GetFullPath($GoldiDataPath)
        terminal_path = $goldiTerminal
        source = $goldiSource
        binary_name = "GoldEngine-GOLDi.ex5"
        preset_name = "G20-GOLDI.set"
        startup_name = "GOLDI.ini"
        account_login = 108098316
        account_server = "XMGlobal-MT5 5"
        fingerprint = "7af1d75e1be54ba4505b32cedcf53f4317dea0a90a2a0636510884d0d408c5b5"
        symbol = "GOLD.i#"
        trade_mode = 0
        order_authority = "ENABLED"
        startup_chart_repair = $true
        allowed_postboot_engine_error_reasons = @()
        spool_name = "GOLDI.jsonl"
    },
    [ordered]@{
        profile_id = "GOLDM"
        data_path = [IO.Path]::GetFullPath($GoldmDataPath)
        terminal_path = $goldmTerminal
        source = $goldmSource
        binary_name = "GoldEngine-GOLDm.ex5"
        preset_name = "G20-GOLDM.set"
        startup_name = "GOLDM.ini"
        account_login = 391425346
        account_server = "XMGlobal-MT5 14"
        fingerprint = "704b383f959298c8a1b1dd5c21665ffb7a022dc9831c7498e68cc37f607d4c24"
        symbol = "GOLDm#"
        trade_mode = 2
        order_authority = "DISABLED"
        startup_chart_repair = $false
        allowed_postboot_engine_error_reasons = @("MANUAL_INTERVENTION_DETECTED")
        spool_name = "GOLDM.jsonl"
    }
)

New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
$commonSpool = Join-Path $env:APPDATA "MetaQuotes\Terminal\Common\Files\bot-ea\spool"
$terminalConfigs = @()
foreach ($binding in $bindings) {
    $expertDirectory = Join-Path $binding.data_path "MQL5\Experts\bot-ea"
    $presetDirectory = Join-Path $binding.data_path "MQL5\Presets"
    New-Item -ItemType Directory -Path $expertDirectory, $presetDirectory -Force | Out-Null
    $destination = Join-Path $expertDirectory $binding.binary_name
    Copy-Item -LiteralPath $binding.source -Destination $destination -Force
    Copy-Item -LiteralPath (Join-Path $repoRoot "config\mql5\presets\$($binding.preset_name)") `
        -Destination (Join-Path $presetDirectory $binding.preset_name) -Force
    $startupPath = Join-Path $OutputRoot $binding.startup_name
    Copy-Item -LiteralPath (Join-Path $repoRoot "config\mql5\startup\$($binding.startup_name)") `
        -Destination $startupPath -Force
    $terminalConfigs += [ordered]@{
        profile_id = $binding.profile_id
        terminal_path = $binding.terminal_path
        arguments = "/config:$startupPath"
        ea_binary_path = $destination
        ea_sha256 = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
        expected_account_login = $binding.account_login
        expected_account_server = $binding.account_server
        expected_profile_fingerprint = $binding.fingerprint
        expected_symbol = $binding.symbol
        expected_trade_mode = $binding.trade_mode
        expected_order_authority = $binding.order_authority
        data_path = $binding.data_path
        startup_chart_repair = $binding.startup_chart_repair
        allowed_postboot_engine_error_reasons = @(
            $binding.allowed_postboot_engine_error_reasons
        )
        spool_path = Join-Path $commonSpool $binding.spool_name
    }
}

if ($BridgeEnabled) {
    if ([string]::IsNullOrWhiteSpace($PythonwPath)) {
        $pythonExe = (& py -3.14 -c "import sys; print(sys.executable)").Trim()
        $PythonwPath = Join-Path (Split-Path -Parent $pythonExe) "pythonw.exe"
    }
    if (-not (Test-Path -LiteralPath $PythonwPath -PathType Leaf)) {
        throw "Bridge pythonw executable is missing: $PythonwPath"
    }
    if (-not (Test-Path -LiteralPath $TelegramSecretPath -PathType Leaf)) {
        throw "Bridge DPAPI token secret is missing: $TelegramSecretPath"
    }
    if ($TelegramAdminChatIds.Count -eq 0 -or
        @($TelegramAdminChatIds | Where-Object { $_ -notmatch '^-?[1-9][0-9]*$' }).Count -gt 0) {
        throw "Bridge requires valid administrator chat IDs"
    }
}

$bridgeRoot = Join-Path $env:ProgramData "bot-ea\bridge"
New-Item -ItemType Directory -Path $bridgeRoot -Force | Out-Null
$bridgeRunner = Join-Path $PSScriptRoot "run-gold-event-bridge.py"
$bridgeHealth = Join-Path $bridgeRoot "health.json"
$bridgeArguments = '"{0}" --goldi-spool "{1}" --goldm-spool "{2}" --database "{3}" --health-path "{4}"' -f `
    $bridgeRunner,
    (Join-Path $commonSpool "GOLDI.jsonl"),
    (Join-Path $commonSpool "GOLDM.jsonl"),
    (Join-Path $bridgeRoot "events.db"),
    $bridgeHealth

$config = [ordered]@{
    schema_version = 1
    production_real_orders = "DISABLED"
    startup_mode = $StartupMode
    poll_seconds = 15
    ea_startup_grace_seconds = 180
    ea_heartbeat_stale_seconds = 3900
    health_path = Join-Path $env:ProgramData "bot-ea\g20\health.json"
    audit_path = Join-Path $env:ProgramData "bot-ea\g20\audit.jsonl"
    lock_marker_path = Join-Path $env:ProgramData "bot-ea\g20\lock-marker.json"
    forbidden_task_names = @(
        "g18 vm goldi probe",
        "g18 vm goldm probe",
        "Gold Global Orchestrator",
        "Gold Global Shutdown Notice"
    )
    terminals = $terminalConfigs
    bridge = [ordered]@{
        enabled = $BridgeEnabled
        executable_path = $PythonwPath
        arguments = $bridgeArguments
        token_secret_path = $TelegramSecretPath
        admin_chat_ids = $TelegramAdminChatIds
        health_path = $bridgeHealth
    }
}
$configPath = Join-Path $OutputRoot "g20-unattended.json"
$config | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $configPath -Encoding UTF8

& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
    -File (Join-Path $PSScriptRoot "g20-unattended-supervisor.ps1") `
    -ConfigPath $configPath -ValidateOnly
if ($LASTEXITCODE -ne 0) {
    throw "Generated G20 configuration did not validate"
}

Write-Output "config_path=$configPath"
Write-Output "goldi_sha256=$($terminalConfigs[0].ea_sha256)"
Write-Output "goldm_sha256=$($terminalConfigs[1].ea_sha256)"
Write-Output "bridge_enabled=$BridgeEnabled"
Write-Output "production_real_orders=DISABLED"
