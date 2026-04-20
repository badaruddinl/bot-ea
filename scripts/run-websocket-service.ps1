$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$srcPath = Join-Path $repoRoot "src"

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

Write-Host "Launching bot-ea websocket service from $repoRoot"
Write-Host "PYTHONPATH=$env:PYTHONPATH"
Write-Host "Startup order: run this websocket service first and keep this window open."
Write-Host "After the service is ready, open another PowerShell window and run scripts/run-qt-gui.ps1."

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
& $pythonCommand -m bot_ea.websocket_service
