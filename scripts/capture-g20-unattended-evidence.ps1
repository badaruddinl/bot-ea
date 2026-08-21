param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Preboot', 'Postboot')]
    [string]$Phase,
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,
    [string]$PrebootPath,
    [string]$TaskName = "BOT-EA G20 Native Supervisor"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-ConfiguredPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [Environment]::ExpandEnvironmentVariables($Path)
}

function Get-StringSha256 {
    param([Parameter(Mandatory = $true)][string]$Value)
    $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-SpoolState {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return [ordered]@{ path = $Path; line_count = 0; length = 0; sha256 = $null }
    }
    $item = Get-Item -LiteralPath $Path
    return [ordered]@{
        path = $Path
        line_count = @(Get-Content -LiteralPath $Path).Count
        length = [long]$item.Length
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function Get-NewSpoolEvents {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][int]$StartLine
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Postboot spool is missing: $Path"
    }
    $lines = @(Get-Content -LiteralPath $Path)
    if ($lines.Count -lt $StartLine) {
        throw "Postboot spool was truncated below its preboot line offset"
    }
    $events = @()
    foreach ($line in @($lines | Select-Object -Skip $StartLine)) {
        if (-not [string]::IsNullOrWhiteSpace([string]$line)) {
            $events += ($line | ConvertFrom-Json)
        }
    }
    return $events
}

function Get-TaskEvidence {
    param([Parameter(Mandatory = $true)][string]$Name)
    $task = Get-ScheduledTask -TaskName $Name -ErrorAction Stop
    $info = Get-ScheduledTaskInfo -TaskName $Name -ErrorAction Stop
    return [ordered]@{
        task_name = $Name
        state = [string]$task.State
        logon_type = [string]$task.Principal.LogonType
        user_id = [string]$task.Principal.UserId
        boot_trigger_count = @(
            $task.Triggers |
                Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskBootTrigger' }
        ).Count
        logon_trigger_count = @(
            $task.Triggers |
                Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' }
        ).Count
        last_run_time_utc = if ($info.LastRunTime.Year -gt 1900) {
            $info.LastRunTime.ToUniversalTime().ToString('o')
        } else { $null }
        # Task Scheduler exposes HRESULT/NTSTATUS values as unsigned 32-bit
        # numbers.  Values with the high bit set (for example 3221225786)
        # overflow System.Int32, so preserve the full value in JSON.
        last_task_result = [long]$info.LastTaskResult
    }
}

function Get-LegacyTaskEvidence {
    param($Names)
    $result = @()
    foreach ($name in @($Names)) {
        $task = Get-ScheduledTask -TaskName ([string]$name) -ErrorAction SilentlyContinue
        $result += [ordered]@{
            task_name = [string]$name
            exists = $null -ne $task
            state = if ($null -ne $task) { [string]$task.State } else { 'MISSING' }
            enabled = if ($null -ne $task) { [bool]$task.Settings.Enabled } else { $false }
        }
    }
    return $result
}

function Get-TerminalProcesses {
    param($Terminals)
    $result = @()
    foreach ($terminal in @($Terminals)) {
        $expected = [IO.Path]::GetFullPath(
            (Resolve-ConfiguredPath ([string]$terminal.terminal_path))
        )
        $matches = @(
            Get-CimInstance Win32_Process -Filter "Name='terminal64.exe'" -ErrorAction SilentlyContinue |
                Where-Object {
                    $_.ExecutablePath -and
                    [IO.Path]::GetFullPath([string]$_.ExecutablePath).Equals(
                        $expected,
                        [StringComparison]::OrdinalIgnoreCase
                    )
                }
        )
        $result += [ordered]@{
            profile_id = [string]$terminal.profile_id
            expected_path = $expected
            process_count = $matches.Count
            pids = @($matches | ForEach-Object { [int]$_.ProcessId })
            session_ids = @($matches | ForEach-Object { [int]$_.SessionId })
        }
    }
    return $result
}

function Get-PythonRoles {
    $result = @()
    $processes = @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -in @('python.exe', 'pythonw.exe') }
    )
    foreach ($process in $processes) {
        $command = [string]$process.CommandLine
        $role = if ($command -match '(?i)(gold_event_bridge|run-gold-event-bridge)') {
            'EVENT_BRIDGE'
        }
        elseif ($command -match '(?i)(gold_orchestrator|run-final-portfolio-worker|goldm_revised|goldm_bear)') {
            'FORBIDDEN_PYTHON_STRATEGY'
        }
        else {
            'OTHER'
        }
        $result += [ordered]@{
            pid = [int]$process.ProcessId
            executable_path = [string]$process.ExecutablePath
            role = $role
            command_sha256 = Get-StringSha256 -Value $command
        }
    }
    return $result
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
    $Value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

$resolvedConfig = [IO.Path]::GetFullPath((Resolve-ConfiguredPath $ConfigPath))
$config = Get-Content -LiteralPath $resolvedConfig -Raw | ConvertFrom-Json
$bootTime = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime()
$capturedAt = [DateTimeOffset]::UtcNow
$spools = [ordered]@{}
foreach ($terminal in @($config.terminals)) {
    $spoolPath = Resolve-ConfiguredPath ([string]$terminal.spool_path)
    $spools[[string]$terminal.profile_id] = Get-SpoolState -Path $spoolPath
}

if ($Phase -eq 'Preboot') {
    $result = [ordered]@{
        schema_version = 1
        gate = 'G20'
        phase = 'PREBOOT'
        captured_at_utc = $capturedAt.ToString('o')
        boot_time_utc = $bootTime.ToString('o')
        production_real_orders = 'DISABLED'
        startup_mode = [string]$config.startup_mode
        task = Get-TaskEvidence -Name $TaskName
        spools = $spools
    }
    Write-AtomicJson -Path $OutputPath -Value $result
    $result | ConvertTo-Json -Compress -Depth 12
    exit 0
}

if ([string]::IsNullOrWhiteSpace($PrebootPath) -or
    -not (Test-Path -LiteralPath $PrebootPath -PathType Leaf)) {
    throw 'Postboot capture requires an existing -PrebootPath'
}
$preboot = Get-Content -LiteralPath $PrebootPath -Raw | ConvertFrom-Json
$newEvents = [ordered]@{}
foreach ($terminal in @($config.terminals)) {
    $profileId = [string]$terminal.profile_id
    $spoolPath = Resolve-ConfiguredPath ([string]$terminal.spool_path)
    $startLine = [int]$preboot.spools.$profileId.line_count
    $newEvents[$profileId] = @(Get-NewSpoolEvents -Path $spoolPath -StartLine $startLine)
}

$healthPath = Resolve-ConfiguredPath ([string]$config.health_path)
if (-not (Test-Path -LiteralPath $healthPath -PathType Leaf)) {
    throw "Supervisor health file is missing: $healthPath"
}
$explorer = Get-Process explorer -ErrorAction SilentlyContinue |
    Sort-Object StartTime | Select-Object -First 1
$result = [ordered]@{
    schema_version = 1
    gate = 'G20'
    phase = 'POSTBOOT'
    captured_at_utc = $capturedAt.ToString('o')
    boot_time_utc = $bootTime.ToString('o')
    production_real_orders = 'DISABLED'
    startup_mode = [string]$config.startup_mode
    interactive_login_observed_at_utc = if ($null -ne $explorer) {
        $explorer.StartTime.ToUniversalTime().ToString('o')
    } else { $null }
    task = Get-TaskEvidence -Name $TaskName
    supervisor_health = Get-Content -LiteralPath $healthPath -Raw | ConvertFrom-Json
    bridge_health = if ([bool]$config.bridge.enabled) {
        $bridgeHealthPath = Resolve-ConfiguredPath ([string]$config.bridge.health_path)
        if (-not (Test-Path -LiteralPath $bridgeHealthPath -PathType Leaf)) {
            throw "Bridge health file is missing: $bridgeHealthPath"
        }
        Get-Content -LiteralPath $bridgeHealthPath -Raw | ConvertFrom-Json
    } else { $null }
    lock_marker = if ([string]$config.startup_mode -eq 'AUTOLOGON_LOCKED_INTERACTIVE') {
        $lockMarkerPath = Resolve-ConfiguredPath ([string]$config.lock_marker_path)
        if (-not (Test-Path -LiteralPath $lockMarkerPath -PathType Leaf)) {
            throw "Autologon lock marker is missing: $lockMarkerPath"
        }
        Get-Content -LiteralPath $lockMarkerPath -Raw | ConvertFrom-Json
    } else { $null }
    terminal_processes = @(Get-TerminalProcesses -Terminals $config.terminals)
    python_roles = @(Get-PythonRoles)
    legacy_tasks = @(Get-LegacyTaskEvidence -Names $config.forbidden_task_names)
    spools = $spools
    new_events = $newEvents
}
Write-AtomicJson -Path $OutputPath -Value $result
$result | ConvertTo-Json -Compress -Depth 12
