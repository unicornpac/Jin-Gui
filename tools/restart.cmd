@echo off
rem Double-click wrapper for restart.ps1. Keeps the window open so errors stay readable.
rem For scripted use, call restart.ps1 directly instead of this file.
setlocal
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
pause
endlocal
exit /b %RC%