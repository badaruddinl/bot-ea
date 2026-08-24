param(
    [string]$TaskName = "Gold Global Orchestrator",
    [string]$ShutdownTaskName = "Gold Global Shutdown Notice"
)

$ErrorActionPreference = "Stop"
foreach ($name in @($TaskName, $ShutdownTaskName)) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($null -ne $task) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Output "$name=REMOVED"
    }
}
