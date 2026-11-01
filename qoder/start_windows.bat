@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [1/5] Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 goto :error
)

call ".venv\Scripts\activate.bat"

echo [2/5] Installing dependencies...
python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :error

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo [i] Created .env from .env.example
)

rem PowerContext probes the app's embedding endpoint at startup, so the app must
rem be listening first. Starting them in the other order leaves memory degraded.

echo [3/5] Starting StudyCoach on 8090...
curl -s -o nul --max-time 1 http://127.0.0.1:8090/health
if not errorlevel 1 goto :app_ready

start "StudyCoach App" cmd /c ".venv\Scripts\python.exe -m app.run"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ok=$false; $i=0; while (-not $ok -and $i -lt 120) { try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 http://127.0.0.1:8090/health -ErrorAction Stop; if ($r.StatusCode -eq 200) { $ok=$true } } catch { Start-Sleep -Milliseconds 500 }; $i++ }; if (-not $ok) { exit 1 }"
if errorlevel 1 goto :app_error

:app_ready
echo [4/5] Checking PowerContext on 8010...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-RestMethod -TimeoutSec 2 http://127.0.0.1:8010/health/ready -ErrorAction Stop; if ($r.status -eq 'ready') { exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 goto :pc_ready

curl -s -o nul --max-time 1 http://127.0.0.1:8010/health/ready
if not errorlevel 1 (
  echo [x] PowerContext is on 8010 but its embedding check is not ready.
  echo     Close the old PowerContext window and run this script again.
  goto :open
)

echo [i] Starting PowerContext in a new window...
start "StudyCoach PowerContext" cmd /c "scripts\start_powercontext.bat"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ok=$false; $i=0; while (-not $ok -and $i -lt 120) { try { $r = Invoke-RestMethod -TimeoutSec 1 http://127.0.0.1:8010/health/ready -ErrorAction Stop; if ($r.status -eq 'ready') { $ok=$true } } catch { Start-Sleep -Milliseconds 500 }; $i++ }; if (-not $ok) { exit 1 }"
if errorlevel 1 echo [x] PowerContext did not become ready. The app still runs; memory will show as disconnected.

:pc_ready
:open
echo [5/5] Opening http://127.0.0.1:8090
start "" http://127.0.0.1:8090
echo.
echo StudyCoach is running in the "StudyCoach App" window.
echo Close that window and the "StudyCoach PowerContext" window to stop.
goto :eof

:app_error
echo [x] StudyCoach did not start. Check the new app window for the error.
exit /b 1

:error
echo [x] Startup failed. Check the messages above.
exit /b 1
