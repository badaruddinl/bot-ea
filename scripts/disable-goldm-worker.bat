@echo off
setlocal
title GOLDM Worker - Disable
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0control-goldm-worker.ps1" -Action Disable
set "GOLDM_EXIT=%ERRORLEVEL%"
echo.
if not "%GOLDM_EXIT%"=="0" echo [ERROR] Worker could not be disabled safely.
pause
exit /b %GOLDM_EXIT%

