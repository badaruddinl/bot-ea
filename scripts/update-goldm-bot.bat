@echo off
setlocal
title GOLDM Bot - Safe Update
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0update-goldm-bot.ps1"
set "GOLDM_EXIT=%ERRORLEVEL%"
echo.
if "%GOLDM_EXIT%"=="2" echo Update cancelled by operator.
if not "%GOLDM_EXIT%"=="0" if not "%GOLDM_EXIT%"=="2" echo [ERROR] Bot update did not complete.
pause
exit /b %GOLDM_EXIT%

