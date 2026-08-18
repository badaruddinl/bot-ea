@echo off
setlocal
title GOLDM Worker - Enable
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0control-goldm-worker.ps1" -Action Enable
set "GOLDM_EXIT=%ERRORLEVEL%"
echo.
if not "%GOLDM_EXIT%"=="0" echo [ERROR] Worker could not be enabled safely.
pause
exit /b %GOLDM_EXIT%

