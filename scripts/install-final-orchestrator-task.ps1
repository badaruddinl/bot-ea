param(
    [string]$TaskName = "Gold Global Orchestrator",
    [string]$ShutdownTaskName = "Gold Global Shutdown Notice",
    [System.Management.Automation.PSCredential]$Credential
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = (& py -3.14 -c "import sys; print(sys.executable)").Trim()
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw "Python 3.14 executable not found"
}
if ($null -eq $Credential) {
    $Credential = Get-Credential -UserName "$env:USERDOMAIN\$env:USERNAME" `
        -Message "Windows credential for running the GOLD orchestrator when logged off"
}
$pythonwExe = Join-Path (Split-Path -Parent $pythonExe) "pythonw.exe"
$runner = Join-Path $PSScriptRoot "run-final-orchestrator.py"
$config = Join-Path $repoRoot "config\final\orchestrator.json"
$arguments = '"{0}" --config "{1}"' -f $runner, $config
$action = New-ScheduledTaskAction -Execute $pythonwExe -Argument $arguments `
    -WorkingDirectory $repoRoot
$startup = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) `
    -MultipleInstances IgnoreNew
$password = $Credential.GetNetworkCredential().Password
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $startup `
    -Settings $settings -User $Credential.UserName -Password $password `
    -RunLevel Highest -Force | Out-Null

$shutdownArguments = '"{0}" --config "{1}" --notify-shutdown' -f $runner, $config
$shutdownCommand = '"{0}" {1}' -f $pythonwExe, $shutdownArguments
$eventQuery = "*[System[Provider[@Name='User32'] and EventID=1074]]"
& schtasks.exe /Create /TN $ShutdownTaskName /TR $shutdownCommand /SC ONEVENT `
    /EC System /MO $eventQuery /RU $Credential.UserName /RP $password /RL HIGHEST /F | Out-Null

Write-Output "$TaskName=INSTALLED"
Write-Output "$ShutdownTaskName=INSTALLED_BEST_EFFORT"
Write-Output "Run with: Start-ScheduledTask -TaskName '$TaskName'"
