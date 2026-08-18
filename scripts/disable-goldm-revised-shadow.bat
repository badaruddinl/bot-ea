@echo off
setlocal
title GOLDM_REVISED Shadow - Disable
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0control-goldm-revised-shadow.ps1" -Action Disable
set "REVISED_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %REVISED_EXIT%
