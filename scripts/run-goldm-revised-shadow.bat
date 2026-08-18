@echo off
setlocal
title GOLDM_REVISED Shadow
python.exe "%~dp0run-goldm-revised-shadow.py" --config "%~dp0..\config\goldm-revised-shadow.json"
set "REVISED_EXIT=%ERRORLEVEL%"
echo.
if not "%REVISED_EXIT%"=="0" echo [ERROR] GOLDM_REVISED shadow stopped with code %REVISED_EXIT%.
pause
exit /b %REVISED_EXIT%
