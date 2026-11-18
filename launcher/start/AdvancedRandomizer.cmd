@echo off
REM Double-click entry point. Starts the window; no console stays behind.
setlocal
cd /d "%~dp0"

set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" set "PS=powershell.exe"

start "" "%PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0launcher\start\launcher.ps1"
exit /b 0
