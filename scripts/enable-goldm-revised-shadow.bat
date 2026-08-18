@echo off
setlocal
title GOLDM_REVISED Shadow - Enable
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0control-goldm-revised-shadow.ps1" -Action Enable
set "REVISED_EXIT=%ERRORLEVEL%"
echo.
if not "%REVISED_EXIT%"=="0" echo [ERROR] GOLDM_REVISED shadow was not enabled.
pause
exit /b %REVISED_EXIT%
