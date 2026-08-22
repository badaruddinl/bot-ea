param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,
    [string]$TaskName = "BOT-EA G20 Native Supervisor",
    [System.Management.Automation.PSCredential]$Credential
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$supervisor = Join-Path $PSScriptRoot "g20-unattended-supervisor.ps1"
if (-not (Test-Path -LiteralPath $supervisor -PathType Leaf)) {
    throw "G20 supervisor script is missing"
}
$resolvedConfig = [IO.Path]::GetFullPath(
    [Environment]::ExpandEnvironmentVariables($ConfigPath)
)
& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
    -File $supervisor -ConfigPath $resolvedConfig -ValidateOnly
if ($LASTEXITCODE -ne 0) {
    throw "G20 configuration validation failed"
}

if ($null -eq $Credential) {
    $Credential = Get-Credential -UserName "$env:USERDOMAIN\$env:USERNAME" `
        -Message "Enter the Windows credential once for unattended MT5 startup"
}

$powerShellExe = Join-Path $PSHOME "powershell.exe"
$arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -ConfigPath "{1}"' -f `
    $supervisor, $resolvedConfig
$action = New-ScheduledTaskAction -Execute $powerShellExe -Argument $arguments `
    -WorkingDirectory (Split-Path -Parent $supervisor)
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = "PT30S"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

$password = $Credential.GetNetworkCredential().Password
try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -User $Credential.UserName -Password $password `
        -RunLevel Highest -Force | Out-Null
}
finally {
    $password = $null
    $Credential = $null
}

$task = Get-ScheduledTask -TaskName $TaskName
if ([string]$task.Principal.LogonType -ne "Password") {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    throw "Task registration did not produce LogonType=Password"
}
if (@($task.Triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskBootTrigger' }).Count -ne 1) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    throw "Task registration did not produce exactly one AtStartup trigger"
}

Write-Output "$TaskName=INSTALLED"
Write-Output "logon_type=$($task.Principal.LogonType)"
Write-Output "trigger=AtStartup"
Write-Output "production_real_orders=DISABLED"
