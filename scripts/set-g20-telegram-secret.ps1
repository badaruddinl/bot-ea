param(
    [string]$SecretPath = "$env:ProgramData\bot-ea\g20\telegram-token.dpapi",
    [System.Security.SecureString]$Token
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($null -eq $Token) {
    $Token = Read-Host "Enter the G20 Telegram bot token" -AsSecureString
}
if ($Token.Length -lt 20) {
    throw "Telegram token is unexpectedly short"
}
$directory = Split-Path -Parent $SecretPath
if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}
$temporary = "$SecretPath.$PID.tmp"
try {
    $Token | ConvertFrom-SecureString | Set-Content -LiteralPath $temporary -Encoding ASCII
    Move-Item -LiteralPath $temporary -Destination $SecretPath -Force
}
finally {
    if (Test-Path -LiteralPath $temporary -PathType Leaf) {
        Remove-Item -LiteralPath $temporary -Force
    }
    $Token.Dispose()
    $Token = $null
}
$acl = Get-Acl -LiteralPath $SecretPath
$acl.SetAccessRuleProtection($true, $false)
$acl.Access | ForEach-Object { [void]$acl.RemoveAccessRule($_) }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$rule = New-Object Security.AccessControl.FileSystemAccessRule(
    $identity, 'FullControl', 'Allow'
)
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $SecretPath -AclObject $acl

Write-Output "telegram_secret=INSTALLED_DPAPI_CURRENT_USER"
Write-Output "secret_path=$SecretPath"
