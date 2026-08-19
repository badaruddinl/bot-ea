@echo off
setlocal
cd /d "%~dp0.."
py -3.14 scripts\run-final-orchestrator.py --config config\final\orchestrator.json --check
endlocal
