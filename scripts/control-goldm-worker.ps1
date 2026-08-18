param(
    [ValidateSet("Enable", "Disable", "Status")]
    [string]$Action = "Status",
    [string]$TaskName = "goldm telegram worker"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-ElevatedCopy {
    $argumentLine = @(
        "-NoLogo"
        "-NoProfile"
        "-ExecutionPolicy Bypass"
        "-File `"$PSCommandPath`""
        "-Action $Action"
        "-TaskName `"$TaskName`""
    ) -join " "
    $process = Start-Process `
        -FilePath "powershell.exe" `
        -Verb RunAs `
        -ArgumentList $argumentLine `
        -Wait `
        -PassThru
    exit $process.ExitCode
}

if (-not (Test-IsAdministrator)) {
    Invoke-ElevatedCopy
}

Import-Module (Join-Path $PSScriptRoot "goldm-deployment-common.psm1") -Force

function Get-WorkerContract {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $actions = @($task.Actions)
    if ($actions.Count -ne 1) {
        throw "Scheduled Task must have exactly one action: $TaskName"
    }
    $scheduledAction = $actions[0]
    return [pscustomobject]@{
        Task = $task
        Execute = [string]$scheduledAction.Execute
        Arguments = [string]$scheduledAction.Arguments
        WorkingDirectory = [string]$scheduledAction.WorkingDirectory
    }
}

function Write-WorkerStatus {
    $contract = Get-WorkerContract
    $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
    $workers = @(Get-GoldMExactWorkerProcesses -ExpectedExecute $contract.Execute)
    Write-Host ""
    Write-Host "GOLDM worker status" -ForegroundColor Cyan
    Write-Host "Task       : $TaskName"
    Write-Host "State      : $($contract.Task.State)"
    Write-Host "Enabled    : $($contract.Task.Settings.Enabled)"
    Write-Host "Worker PID : $(@($workers.ProcessId) -join ', ')"
    Write-Host "Last result: $($info.LastTaskResult)"
    return [pscustomobject]@{
        Contract = $contract
        Workers = $workers
    }
}

try {
    switch ($Action) {
        "Disable" {
            $status = Write-WorkerStatus
            if (
                [string]$status.Contract.Task.State -eq "Disabled" -and
                $status.Contract.Task.Settings.Enabled -eq $false -and
                @($status.Workers).Count -eq 0
            ) {
                Write-Host "Worker already disabled and stopped." -ForegroundColor Yellow
            }
            else {
                [void](Disable-GoldMScheduledTaskAndWait -TaskName $TaskName)
                Write-Host "Worker disabled and fully stopped." -ForegroundColor Green
            }
            [void](Write-WorkerStatus)
        }
        "Enable" {
            $status = Write-WorkerStatus
            if (
                [string]$status.Contract.Task.State -eq "Running" -and
                $status.Contract.Task.Settings.Enabled -eq $true
            ) {
                [void](Assert-GoldMScheduledTaskRunning `
                    -TaskName $TaskName `
                    -ExpectedExecute $status.Contract.Execute `
                    -ExpectedArguments $status.Contract.Arguments `
                    -ExpectedWorkingDirectory $status.Contract.WorkingDirectory)
                Write-Host "Worker already enabled and running." -ForegroundColor Yellow
            }
            else {
                [void](Start-GoldMScheduledTaskAndVerify `
                    -TaskName $TaskName `
                    -ExpectedExecute $status.Contract.Execute `
                    -ExpectedArguments $status.Contract.Arguments `
                    -ExpectedWorkingDirectory $status.Contract.WorkingDirectory)
                Write-Host "Worker enabled and verified running." -ForegroundColor Green
            }
            [void](Write-WorkerStatus)
        }
        "Status" {
            [void](Write-WorkerStatus)
        }
    }
    exit 0
}
catch {
    Write-Host ""
    Write-Host "GOLDM worker operation failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

