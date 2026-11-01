#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"
mkdir -p data

if [ ! -x ".venv/bin/python" ]; then
  echo "[1/5] Creating virtual environment..."
  "$PYTHON_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "[2/5] Installing dependencies..."
python -m pip install --disable-pip-version-check -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "[i] Created .env from .env.example"
fi

# PowerContext probes the app's embedding endpoint at startup, so the app must
# be listening first. Starting them in the other order leaves memory degraded.

APP_PID=""
PC_PID=""
cleanup() {
  if [ -n "$PC_PID" ]; then kill "$PC_PID" 2>/dev/null || true; fi
  if [ -n "$APP_PID" ]; then kill "$APP_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM

echo "[3/5] Starting StudyCoach on 8090..."
if curl -fsS --max-time 1 http://127.0.0.1:8090/health >/dev/null 2>&1; then
  echo "[i] StudyCoach is already running on 8090."
else
  python -m app.run > data/app.log 2>&1 &
  APP_PID=$!
  for _ in $(seq 1 120); do
    if curl -fsS --max-time 1 http://127.0.0.1:8090/health >/dev/null 2>&1; then
      break
    fi
    sleep 0.5
  done
  if ! curl -fsS --max-time 1 http://127.0.0.1:8090/health >/dev/null 2>&1; then
    echo "[x] StudyCoach did not start. See data/app.log."
    exit 1
  fi
fi

echo "[4/5] Checking PowerContext on 8010..."
if curl -fsS --max-time 1 http://127.0.0.1:8010/health/ready >/dev/null 2>&1 \
  && curl -fsS --max-time 1 http://127.0.0.1:8010/health/ready | grep -q '"status":"ready"'; then
  echo "[i] PowerContext is already ready on 8010."
else
  ./scripts/start_powercontext.sh > data/powercontext.log 2>&1 &
  PC_PID=$!
  for _ in $(seq 1 120); do
    if curl -fsS --max-time 1 http://127.0.0.1:8010/health/ready 2>/dev/null | grep -q '"status":"ready"'; then
      break
    fi
    sleep 0.5
  done
  if ! curl -fsS --max-time 1 http://127.0.0.1:8010/health/ready 2>/dev/null | grep -q '"status":"ready"'; then
    echo "[x] PowerContext did not become ready. The app still runs; memory will show as disconnected."
  fi
fi

echo "[5/5] Opening http://127.0.0.1:8090"
if command -v open >/dev/null 2>&1; then
  open http://127.0.0.1:8090
fi

echo "StudyCoach is running. Press Ctrl+C to stop the services started by this script."
if [ -n "$APP_PID" ]; then
  wait "$APP_PID"
elif [ -n "$PC_PID" ]; then
  wait "$PC_PID"
fi
