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

Write-Host "Legacy launcher detected."
Write-Host "Redirecting to Qt operator app from $repoRoot"
Write-Host "PYTHONPATH=$env:PYTHONPATH"

python -m bot_ea.qt_app
