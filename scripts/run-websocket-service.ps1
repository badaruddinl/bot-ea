$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "run-qt-gui.ps1") -BootstrapOnly

Invoke-BotEaPythonModule -Module "bot_ea.websocket_service" -WriteBanner {
    param($launcher)
    Write-Host "Launching bot-ea websocket service from $($launcher.RepoRoot)"
    Write-Host "PYTHONPATH=$($launcher.PythonPath)"
    Write-Host "Debug-only backend entrypoint."
    Write-Host "Normal operator flow should start from scripts/run-qt-gui.ps1."
}
