@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1"
set "taskExit=%ERRORLEVEL%"
if not "%taskExit%"=="0" pause
endlocal & exit /b %taskExit%
