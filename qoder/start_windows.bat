@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 goto :error
)

call ".venv\Scripts\activate.bat"

echo [2/3] Installing dependencies...
python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :error

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo [i] Created .env from .env.example
)

echo [3/3] Starting http://127.0.0.1:8090
python -m uvicorn app.main:app --host 127.0.0.1 --port 8090
goto :eof

:error
echo [x] Startup failed. Check the messages above.
exit /b 1
