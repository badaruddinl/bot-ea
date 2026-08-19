@echo off
setlocal
cd /d "%~dp0.."
py -3.14 scripts\run-final-portfolio-worker.py --config config\final\goldm\worker.json --once
endlocal
