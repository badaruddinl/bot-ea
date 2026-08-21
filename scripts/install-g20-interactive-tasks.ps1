param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,
    [string]$SupervisorTaskName = "BOT-EA G20 Native Supervisor",
    [string]$LockTaskName = "BOT-EA G20 Immediate Lock",
    [string]$UserName = "$env:USERDOMAIN\$env:USERNAME",
    [switch]$AcknowledgeLsaSecretRisk
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $AcknowledgeLsaSecretRisk) {
    throw "Explicit -AcknowledgeLsaSecretRisk is required"
}
$resolvedConfig = [IO.Path]::GetFullPath(
    [Environment]::ExpandEnvironmentVariables($ConfigPath)
)
$config = Get-Content -LiteralPath $resolvedConfig -Raw | ConvertFrom-Json
if ([string]$config.production_real_orders -ne 'DISABLED') {
    throw "Production REAL authority must remain DISABLED"
}
if ([string]$config.startup_mode -ne 'AUTOLOGON_LOCKED_INTERACTIVE') {
    throw "Config startup_mode must be AUTOLOGON_LOCKED_INTERACTIVE"
}

$winlogonPath = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
$winlogon = Get-ItemProperty -LiteralPath $winlogonPath
if ([string]$winlogon.AutoAdminLogon -ne '1') {
    throw "Microsoft Autologon is not enabled"
}
$shortUser = $UserName.Split('\')[-1]
if ([string]$winlogon.DefaultUserName -ne $shortUser) {
    throw "Autologon user does not match the task user"
}
if ($null -ne $winlogon.PSObject.Properties['DefaultPassword']) {
    throw "Plaintext Winlogon DefaultPassword is forbidden; use Sysinternals Autologon"
}

$supervisor = Join-Path $PSScriptRoot "g20-unattended-supervisor.ps1"
$lockScript = Join-Path $PSScriptRoot "g20-lock-workstation.ps1"
& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
    -File $supervisor -ConfigPath $resolvedConfig -ValidateOnly
if ($LASTEXITCODE -ne 0) {
    throw "G20 configuration validation failed"
}

$powerShellExe = Join-Path $PSHOME "powershell.exe"
$supervisorArguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -ConfigPath "{1}"' -f `
    $supervisor, $resolvedConfig
$supervisorAction = New-ScheduledTaskAction -Execute $powerShellExe `
    -Argument $supervisorArguments -WorkingDirectory $PSScriptRoot
$supervisorTrigger = New-ScheduledTaskTrigger -AtLogOn -User $UserName
$supervisorTrigger.Delay = 'PT5S'
$principal = New-ScheduledTaskPrincipal -UserId $UserName -LogonType Interactive `
    -RunLevel Highest
$supervisorSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $SupervisorTaskName -Action $supervisorAction `
    -Trigger $supervisorTrigger -Principal $principal -Settings $supervisorSettings `
    -Force | Out-Null

$lockArguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -MarkerPath "{1}"' -f `
    $lockScript, [string]$config.lock_marker_path
$lockAction = New-ScheduledTaskAction -Execute $powerShellExe -Argument $lockArguments `
    -WorkingDirectory $PSScriptRoot
$lockTrigger = New-ScheduledTaskTrigger -AtLogOn -User $UserName
$lockTrigger.Delay = 'PT20S'
$lockSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $LockTaskName -Action $lockAction -Trigger $lockTrigger `
    -Principal $principal -Settings $lockSettings -Force | Out-Null

foreach ($name in @($SupervisorTaskName, $LockTaskName)) {
    $task = Get-ScheduledTask -TaskName $name
    if ([string]$task.Principal.LogonType -ne 'Interactive') {
        throw "$name LogonType is not Interactive"
    }
    if (@($task.Triggers | Where-Object {
                $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger'
            }).Count -ne 1) {
        throw "$name does not have exactly one AtLogOn trigger"
    }
}

Write-Output "$SupervisorTaskName=INSTALLED_INTERACTIVE"
Write-Output "$LockTaskName=INSTALLED_INTERACTIVE"
Write-Output "startup_mode=AUTOLOGON_LOCKED_INTERACTIVE"
Write-Output "production_real_orders=DISABLED"
