@echo off
setlocal
title GOLDM Worker - Status
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0control-goldm-worker.ps1" -Action Status
set "GOLDM_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %GOLDM_EXIT%

