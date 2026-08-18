@echo off
setlocal
title GOLDM_REVISED Shadow - Status
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0control-goldm-revised-shadow.ps1" -Action Status
set "REVISED_EXIT=%ERRORLEVEL%"
echo.
pause
exit /b %REVISED_EXIT%
