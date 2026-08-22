param(
    [string]$MarkerPath = "$env:ProgramData\bot-ea\g20\lock-marker.json"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not ("G20.NativeMethods" -as [type])) {
    Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;
namespace G20 {
    public static class NativeMethods {
        [DllImport("user32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool LockWorkStation();
    }
}
"@
}

$boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime()
$requestedAt = [DateTimeOffset]::UtcNow
$locked = [G20.NativeMethods]::LockWorkStation()
$payload = [ordered]@{
    schema_version = 1
    boot_time_utc = $boot.ToString('o')
    lock_requested_at_utc = $requestedAt.ToString('o')
    lock_requested = $locked
    windows_identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    session_id = [Diagnostics.Process]::GetCurrentProcess().SessionId
    production_real_orders = "DISABLED"
}
$directory = Split-Path -Parent $MarkerPath
if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}
$temporary = "$MarkerPath.$PID.tmp"
$payload | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $temporary -Encoding UTF8
Move-Item -LiteralPath $temporary -Destination $MarkerPath -Force
if (-not $locked) {
    throw "LockWorkStation returned false"
}
Write-Output "workstation_lock=REQUESTED"
Write-Output "production_real_orders=DISABLED"
