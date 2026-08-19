param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("start", "stop", "status")]
    [string]$Action
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $repoRoot "runtime_data\final\processes"
$pythonExe = (& py -3.14 -c "import sys; print(sys.executable)").Trim()
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw "Python 3.14 executable not found"
}
$workers = @(
    @{ Name = "goldi"; Config = "config\final\goldi\worker.json" },
    @{ Name = "goldm"; Config = "config\final\goldm\worker.json" }
)
New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null

function Get-WorkerProcess([string]$name) {
    $pidPath = Join-Path $runtimeRoot "$name.pid"
    if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) { return $null }
    $workerPid = [int](Get-Content -LiteralPath $pidPath -Raw)
    $candidate = Get-Process -Id $workerPid -ErrorAction SilentlyContinue
    if ($null -eq $candidate) { return $null }
    if ($candidate.Path -ne $pythonExe) { return $null }
    return $candidate
}

foreach ($worker in $workers) {
    $name = $worker.Name
    $pidPath = Join-Path $runtimeRoot "$name.pid"
    $process = Get-WorkerProcess $name
    if ($Action -eq "status") {
        if ($null -eq $process) { Write-Output "$name=STOPPED" }
        else { Write-Output "$name=RUNNING pid=$($process.Id)" }
        continue
    }
    if ($Action -eq "stop") {
        if ($null -ne $process) { Stop-Process -Id $process.Id }
        if (Test-Path -LiteralPath $pidPath) { Remove-Item -LiteralPath $pidPath }
        Write-Output "$name=STOPPED"
        continue
    }
    if ($null -ne $process) {
        Write-Output "$name=ALREADY_RUNNING pid=$($process.Id)"
        continue
    }
    $arguments = @(
        "scripts\run-final-portfolio-worker.py",
        "--config",
        $worker.Config
    )
    $started = Start-Process -FilePath $pythonExe -ArgumentList $arguments `
        -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru
    Set-Content -LiteralPath $pidPath -Value $started.Id -Encoding ascii
    Write-Output "$name=STARTED pid=$($started.Id)"
}
