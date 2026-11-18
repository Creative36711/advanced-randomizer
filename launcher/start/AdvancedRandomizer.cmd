@echo off
REM Double-click entry point.
REM
REM ASCII only on purpose: cmd.exe reads this file in an OEM code page, so any
REM Cyrillic here becomes rubbish on a machine with a different code page.  The
REM Russian messages come from show-failure.ps1, which is Unicode.
setlocal EnableExtensions
cd /d "%~dp0"

set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" set "PS=powershell.exe"

set "STATEDIR=%LOCALAPPDATA%\AdvancedRandomizer"
set "READY=%STATEDIR%\launcher-ready"
set "LOG=%STATEDIR%\launcher.log"
if not exist "%STATEDIR%" mkdir "%STATEDIR%" >nul 2>&1
if exist "%READY%" del /q "%READY%" >nul 2>&1

REM The window script sits NEXT TO this file.  An earlier version appended
REM "launcher\start\launcher.ps1" to this already-nested folder, so the path
REM pointed at a file that does not exist: PowerShell exited before drawing
REM anything, and cmd.exe closed without a word.
start "" "%PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0launcher.ps1"

REM Wait up to ~20 seconds for the window to announce itself.  `ping` is the
REM sleep because `timeout /t` returns immediately when stdin is redirected.
set "WAITED=0"
:wait
if exist "%READY%" goto :running
if %WAITED% GEQ 20 goto :failed
set /a WAITED=%WAITED%+1
ping -n 2 127.0.0.1 >nul 2>&1
goto :wait

:running
endlocal
exit /b 0

:failed
"%PS%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0show-failure.ps1" -Log "%LOG%" -Launcher "%~dp0launcher.ps1"
endlocal
exit /b 1
