param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TaskName = "goldm telegram worker",
    [string]$PythonExecutable = "py",
    [string]$MetaEditorPath = "C:\Program Files\MetaTrader 5\MetaEditor64.exe"
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $RepoRoot

foreach ($command in @("git", $PythonExecutable)) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $command"
    }
}
if (-not (Test-Path -LiteralPath $MetaEditorPath)) {
    throw "MetaTrader 5 / MetaEditor not found: $MetaEditorPath"
}

$version = & $PythonExecutable -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
if ($LASTEXITCODE -ne 0 -or [version]$version -lt [version]"3.11") {
    throw "Python 3.11 or newer is required; found $version"
}

& $PythonExecutable -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $PythonExecutable -m pip install -e ".[live]"
if ($LASTEXITCODE -ne 0) { throw "project install failed" }

$envPath = Join-Path $RepoRoot ".env"
if (-not (Test-Path -LiteralPath $envPath)) {
    Copy-Item -LiteralPath (Join-Path $RepoRoot ".env.example") -Destination $envPath
    throw ".env was created from .env.example. Fill Telegram secrets/admin IDs, then rerun bootstrap."
}

$requiredKeys = @("TELEGRAM_BOT_TOKEN", "TELEGRAM_ADMIN_CHAT_IDS")
$envText = Get-Content -LiteralPath $envPath -Raw
foreach ($key in $requiredKeys) {
    if ($envText -notmatch "(?m)^$key=.+$") {
        throw "Missing required .env key: $key"
    }
}

& $PythonExecutable -c "from goldm_signal.storage import SignalStore; SignalStore(r'runtime_data/goldm_signal.db').initialize(); print('database=ready')"
if ($LASTEXITCODE -ne 0) { throw "database initialization failed" }

$pythonPath = & $PythonExecutable -c "import sys; print(sys.executable)"
$pythonwPath = Join-Path (Split-Path -Parent $pythonPath.Trim()) "pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonwPath)) {
    throw "pythonw.exe not found next to $pythonPath"
}
$action = New-ScheduledTaskAction `
    -Execute $pythonwPath `
    -Argument "-m goldm_signal.notify.cli" `
    -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Output "BOOTSTRAP_OK"
Write-Output "next=Run scripts\deploy-goldm-windows-vm.ps1, log in to MT5, attach EA to GOLD.i# M15 once, and save the profile."
