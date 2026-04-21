$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "run-qt-gui.ps1") -BootstrapOnly

Invoke-BotEaPythonModule -Module "bot_ea.qt_app" -WriteBanner {
    param($launcher)
    Write-Host "Legacy launcher detected."
    Write-Host "Redirecting to Qt operator app from $($launcher.RepoRoot)"
    Write-Host "PYTHONPATH=$($launcher.PythonPath)"
    Write-Host "This legacy alias preserves Qt-first startup behavior."
}
