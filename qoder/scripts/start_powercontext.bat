@echo off
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\powercontext.exe" (
  echo PowerContext is not installed yet. Run start_windows.bat first.
  exit /b 1
)

set "POWERCONTEXT_HOME=%CD%\data\powercontext"
if not exist "%POWERCONTEXT_HOME%" mkdir "%POWERCONTEXT_HOME%"

echo PowerContext starting on http://127.0.0.1:8000
".venv\Scripts\powercontext.exe" server run
