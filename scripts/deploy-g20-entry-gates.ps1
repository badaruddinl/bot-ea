param(
    [string]$ConfigPath = "$env:ProgramData\bot-ea\g20\g20-unattended.json",
    [string]$TaskName = "BOT-EA G20 Native Supervisor",
    [string]$MetaEditorPath = "C:\Program Files\MetaTrader 5\MetaEditor64.exe",
    [switch]$AcknowledgeGatedRealAuthority
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $AcknowledgeGatedRealAuthority) {
    throw "Use -AcknowledgeGatedRealAuthority for the human-approved GATED deployment"
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$configPath = [IO.Path]::GetFullPath($ConfigPath)
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$terminals = @($config.terminals)
if (($terminals | ForEach-Object { [string]$_.profile_id } | Sort-Object) -join ',' -ne
    'GOLDI,GOLDM') {
    throw "Deployment requires exactly GOLDI and GOLDM"
}
$goldi = $terminals | Where-Object profile_id -eq 'GOLDI'
$goldm = $terminals | Where-Object profile_id -eq 'GOLDM'
if ([int]$goldi.expected_trade_mode -ne 0 -or [int]$goldm.expected_trade_mode -ne 2) {
    throw "Trade-mode binding mismatch"
}
if ([string]$goldi.expected_symbol -ne 'GOLD.i#' -or
    [string]$goldm.expected_symbol -ne 'GOLDm#') {
    throw "Symbol binding mismatch"
}

$buildEvidence = '.ci-evidence\entry-gate-deploy'
& (Join-Path $PSScriptRoot 'validate-g21-mql5-build.ps1') `
    -MetaEditorPath $MetaEditorPath -EvidenceRoot $buildEvidence
if ($LASTEXITCODE -ne 0) {
    throw "MQL5 entry-gate build failed"
}

$compiled = @{
    GOLDI = Join-Path $repoRoot 'mt5\Experts\bot-ea\GoldEngine-GOLDi.ex5'
    GOLDM = Join-Path $repoRoot 'mt5\Experts\bot-ea\GoldEngine-GOLDm.ex5'
}
foreach ($profile in 'GOLDI', 'GOLDM') {
    if (-not (Test-Path -LiteralPath $compiled[$profile] -PathType Leaf)) {
        throw "$profile compiled binary is missing"
    }
}

$rollbackRoot = Join-Path $env:ProgramData (
    "bot-ea\g20\rollback-entry-gate-" + [DateTimeOffset]::UtcNow.ToString('yyyyMMddHHmmss')
)
New-Item -ItemType Directory -Path $rollbackRoot -Force | Out-Null
Copy-Item -LiteralPath $configPath -Destination (Join-Path $rollbackRoot 'g20-unattended.json')
foreach ($terminal in $terminals) {
    Copy-Item -LiteralPath ([string]$terminal.ea_binary_path) `
        -Destination (Join-Path $rollbackRoot "$($terminal.profile_id).ex5")
}
$presetTargets = @{}
$startupTargets = @{}
foreach ($terminal in $terminals) {
    $profile = [string]$terminal.profile_id
    $dataPath = ''
    if ($null -ne $terminal.PSObject.Properties['data_path'] -and
        -not [string]::IsNullOrWhiteSpace([string]$terminal.data_path)) {
        $dataPath = [IO.Path]::GetFullPath([string]$terminal.data_path)
    }
    else {
        $expertDirectory = Split-Path -Parent ([string]$terminal.ea_binary_path)
        $expertsDirectory = Split-Path -Parent $expertDirectory
        $mql5Directory = Split-Path -Parent $expertsDirectory
        $dataPath = [IO.Path]::GetFullPath((Split-Path -Parent $mql5Directory))
    }
    $presetTargets[$profile] = Join-Path $dataPath `
        "MQL5\Presets\G20-$profile.set"
    $argument = [string]$terminal.arguments
    if ($argument -notmatch '^/config:(.+)$') {
        throw "$profile terminal arguments do not contain a profile-locked /config path"
    }
    $startupTargets[$profile] = [IO.Path]::GetFullPath($Matches[1])
    Copy-Item -LiteralPath $presetTargets[$profile] `
        -Destination (Join-Path $rollbackRoot "$profile.set")
    Copy-Item -LiteralPath $startupTargets[$profile] `
        -Destination (Join-Path $rollbackRoot "$profile.ini")
}

try {
    Stop-ScheduledTask -TaskName $TaskName
    $managedRunners = @(
        [string]$config.bridge.runner_path,
        [string]$config.telegram_control.runner_path
    )
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
        Where-Object {
            $line = [string]$_.CommandLine
            @($managedRunners | Where-Object {
                    $line.IndexOf($_, [StringComparison]::OrdinalIgnoreCase) -ge 0
                }).Count -gt 0
        } |
        ForEach-Object { Stop-Process -Id ([int]$_.ProcessId) -Force }
    foreach ($terminal in $terminals) {
        $expected = [IO.Path]::GetFullPath([string]$terminal.terminal_path)
        Get-CimInstance Win32_Process -Filter "Name='terminal64.exe'" |
            Where-Object {
                $_.ExecutablePath -and
                [IO.Path]::GetFullPath([string]$_.ExecutablePath).Equals(
                    $expected,
                    [StringComparison]::OrdinalIgnoreCase
                )
            } |
            ForEach-Object { Stop-Process -Id ([int]$_.ProcessId) -Force }
    }

    foreach ($terminal in $terminals) {
        $profile = [string]$terminal.profile_id
        Copy-Item -LiteralPath $compiled[$profile] `
            -Destination ([string]$terminal.ea_binary_path) -Force
        $terminal.ea_sha256 = (
            Get-FileHash -LiteralPath ([string]$terminal.ea_binary_path) -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        $presetSource = Join-Path $repoRoot "config\mql5\presets\G20-$profile.set"
        Copy-Item -LiteralPath $presetSource -Destination $presetTargets[$profile] -Force
        Copy-Item -LiteralPath (Join-Path $repoRoot "config\mql5\startup\$profile.ini") `
            -Destination $startupTargets[$profile] -Force
    }

    $config.production_real_orders = 'GATED'
    $goldm.expected_order_authority = 'ENABLED'
    $goldm.allowed_postboot_engine_error_reasons = @()
    $entryGateRoot = Join-Path $env:APPDATA `
        "MetaQuotes\Terminal\Common\Files\bot-ea\control"
    if ($null -eq $config.telegram_control.PSObject.Properties['entry_gate_root']) {
        $config.telegram_control | Add-Member -NotePropertyName entry_gate_root `
            -NotePropertyValue $entryGateRoot
    }
    else {
        $config.telegram_control.entry_gate_root = $entryGateRoot
    }
    $temporary = "$configPath.tmp"
    $config | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $configPath -Force
    Start-ScheduledTask -TaskName $TaskName
}
catch {
    Copy-Item -LiteralPath (Join-Path $rollbackRoot 'g20-unattended.json') `
        -Destination $configPath -Force
    foreach ($terminal in $terminals) {
        $profile = [string]$terminal.profile_id
        Copy-Item -LiteralPath (Join-Path $rollbackRoot "$($terminal.profile_id).ex5") `
            -Destination ([string]$terminal.ea_binary_path) -Force
        Copy-Item -LiteralPath (Join-Path $rollbackRoot "$profile.set") `
            -Destination $presetTargets[$profile] -Force
        Copy-Item -LiteralPath (Join-Path $rollbackRoot "$profile.ini") `
            -Destination $startupTargets[$profile] -Force
    }
    Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    throw
}

Write-Output "deployment=PASS"
Write-Output "production_real_orders=GATED"
Write-Output "goldi_entry_gate=OFF"
Write-Output "goldm_entry_gate=OFF"
Write-Output "rollback=$rollbackRoot"
