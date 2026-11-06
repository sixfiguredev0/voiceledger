@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
if not exist ".venv\Scripts\python.exe" (
  echo Run Setup.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m voiceledger.cli launch
set "taskExit=%ERRORLEVEL%"
if not "%taskExit%"=="0" pause
endlocal & exit /b %taskExit%
