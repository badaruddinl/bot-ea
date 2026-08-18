param(
    [ValidateSet("Enable", "Disable", "Status")]
    [string]$Action = "Status",
    [string]$TaskName = "goldm revised shadow"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-RevisedTask {
    return Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
}

try {
    $task = Get-RevisedTask
    if ($Action -eq "Status") {
        $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
        Write-Host "GOLDM_REVISED shadow status" -ForegroundColor Cyan
        Write-Host "Task       : $TaskName"
        Write-Host "State      : $($task.State)"
        Write-Host "Enabled    : $($task.Settings.Enabled)"
        Write-Host "Last result: $($info.LastTaskResult)"
        exit 0
    }
    if ($Action -eq "Enable") {
        Enable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
        Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        Write-Host "GOLDM_REVISED shadow task enabled and started." -ForegroundColor Green
        exit 0
    }
    Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Write-Host "GOLDM_REVISED shadow task disabled." -ForegroundColor Yellow
    exit 0
}
catch {
    Write-Host "GOLDM_REVISED shadow operation failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
