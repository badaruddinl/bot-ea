param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$PythonPath = "python.exe",
    [string]$TaskName = "goldm revised shadow",
    [string]$OperatorUser = "$env:USERDOMAIN\$env:USERNAME"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$runner = Join-Path $RepoRoot "scripts\run-goldm-revised-shadow.py"
$config = Join-Path $RepoRoot "config\goldm-revised-shadow.json"
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) { throw "REVISED runner not found: $runner" }
if (-not (Test-Path -LiteralPath $config -PathType Leaf)) { throw "REVISED config not found: $config" }

$arguments = "`"$runner`" --config `"$config`""
$action = New-ScheduledTaskAction -Execute $PythonPath -Argument $arguments -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $OperatorUser
$principal = New-ScheduledTaskPrincipal -UserId $OperatorUser -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Disable-ScheduledTask -TaskName $TaskName | Out-Null
Write-Host "Registered disabled task: $TaskName" -ForegroundColor Green
