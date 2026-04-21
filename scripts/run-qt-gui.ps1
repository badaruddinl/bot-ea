$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$srcPath = Join-Path $repoRoot "src"
Set-Location -LiteralPath $repoRoot

if (-not (Test-Path -LiteralPath $srcPath)) {
    throw "src path not found: $srcPath"
}

$existingPythonPath = $env:PYTHONPATH
if ([string]::IsNullOrWhiteSpace($existingPythonPath)) {
    $env:PYTHONPATH = $srcPath
}
else {
    $env:PYTHONPATH = "$srcPath;$existingPythonPath"
}

Write-Host "Launching bot-ea Qt desktop GUI from $repoRoot"
Write-Host "PYTHONPATH=$env:PYTHONPATH"
Write-Host "The Qt app is the primary operator entrypoint."
Write-Host "It can manage the local websocket backend itself during normal use."
Write-Host "Use scripts/run-websocket-service.ps1 only for backend debugging."

$pythonCommand = $null
foreach ($candidate in @("python3.14", "python")) {
    try {
        $pythonCommand = (Get-Command $candidate -ErrorAction Stop).Source
        break
    }
    catch {
        continue
    }
}

if (-not $pythonCommand) {
    throw "No Python interpreter found. Install Python 3.14 or ensure python is on PATH."
}

Write-Host "Python=$pythonCommand"
& $pythonCommand -m bot_ea.qt_app
