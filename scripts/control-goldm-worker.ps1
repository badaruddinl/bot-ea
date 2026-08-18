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

function Get-LegacyWorkerProcesses {
    $deploymentRoot = [System.IO.Path]::GetFullPath(
        (Split-Path -Parent $RepoRoot)
    ).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    $legacyRootPrefix = $deploymentRoot + [System.IO.Path]::DirectorySeparatorChar + "app-backup-"
    $legacyWrapperSuffix = [System.IO.Path]::DirectorySeparatorChar + "telegram-worker.pyw"
    $matches = @()
    foreach ($candidate in @(
        Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" -ErrorAction Stop
    )) {
        if (-not $candidate.CommandLine) {
            continue
        }
        $commandLine = [string]$candidate.CommandLine
        if (
            $commandLine.IndexOf($legacyRootPrefix, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            $commandLine.IndexOf($legacyWrapperSuffix, [StringComparison]::OrdinalIgnoreCase) -ge 0
        ) {
            $matches += $candidate
        }
    }
    return $matches
}

function Stop-LegacyWorkerProcessesAndWait {
    param(
        [Parameter(Mandatory = $true)][object[]]$Processes,
        [int]$TimeoutSeconds = 15
    )
    $processIds = @()
    foreach ($candidate in @($Processes | Sort-Object ProcessId -Unique)) {
        $processId = [int]$candidate.ProcessId
        $current = @(
            Get-CimInstance Win32_Process `
                -Filter "ProcessId = $processId" `
                -ErrorAction Stop
        )
        if ($current.Count -eq 0) {
            continue
        }
        if (
            $current.Count -ne 1 -or
            -not [string]::Equals(
                [string]$current[0].CommandLine,
                [string]$candidate.CommandLine,
                [StringComparison]::Ordinal
            )
        ) {
            throw "Legacy GOLDM worker PID identity changed before stop: $processId"
        }
        Stop-Process -Id $processId -Force -ErrorAction Stop
        $processIds += $processId
    }
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $legacyProcessIds = @((Get-LegacyWorkerProcesses).ProcessId)
        $remaining = @($processIds | Where-Object { $_ -in $legacyProcessIds })
        if ($remaining.Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Legacy GOLDM worker processes did not stop: $($remaining -join ', ')"
}

function Write-WorkerStatus {
    $contract = Get-WorkerContract
    $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
    $workers = @(
        Get-GoldMExactWorkerProcesses `
            -ExpectedExecute $contract.Execute `
            -ExpectedArguments $contract.Arguments
    )
    $legacyWorkers = @(Get-LegacyWorkerProcesses)
    Write-Host ""
    Write-Host "GOLDM worker status" -ForegroundColor Cyan
    Write-Host "Task       : $TaskName"
    Write-Host "State      : $($contract.Task.State)"
    Write-Host "Enabled    : $($contract.Task.Settings.Enabled)"
    Write-Host "Worker PID : $(@($workers.ProcessId) -join ', ')"
    Write-Host "Legacy PID : $(@($legacyWorkers.ProcessId) -join ', ')"
    Write-Host "Last result: $($info.LastTaskResult)"
    return [pscustomobject]@{
        Contract = $contract
        Workers = $workers
        LegacyWorkers = $legacyWorkers
    }
}

try {
    switch ($Action) {
        "Disable" {
            $status = Write-WorkerStatus
            if (
                [string]$status.Contract.Task.State -eq "Disabled" -and
                $status.Contract.Task.Settings.Enabled -eq $false -and
                @($status.Workers).Count -eq 0 -and
                @($status.LegacyWorkers).Count -eq 0
            ) {
                Write-Host "Worker already disabled and stopped." -ForegroundColor Yellow
            }
            else {
                [void](Disable-GoldMScheduledTaskAndWait -TaskName $TaskName)
                if (@($status.LegacyWorkers).Count -gt 0) {
                    Stop-LegacyWorkerProcessesAndWait -Processes @($status.LegacyWorkers)
                }
                Write-Host "Worker disabled and fully stopped." -ForegroundColor Green
            }
            $finalStatus = Write-WorkerStatus
            if (
                @($finalStatus.Workers).Count -ne 0 -or
                @($finalStatus.LegacyWorkers).Count -ne 0
            ) {
                throw "Worker disable verification found a remaining process"
            }
        }
        "Enable" {
            $status = Write-WorkerStatus
            if (@($status.LegacyWorkers).Count -gt 0) {
                Write-Host "Stopping legacy backup worker before enabling current task." -ForegroundColor Yellow
                Stop-LegacyWorkerProcessesAndWait -Processes @($status.LegacyWorkers)
                $status = Write-WorkerStatus
            }
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
            $finalStatus = Write-WorkerStatus
            if (@($finalStatus.Workers).Count -ne 1) {
                throw "Worker enable verification expected exactly one current task process"
            }
            if (@($finalStatus.LegacyWorkers).Count -ne 0) {
                throw "Worker enable verification found a legacy backup process"
            }
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
