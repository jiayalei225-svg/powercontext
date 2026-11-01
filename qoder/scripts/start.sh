#!/usr/bin/env bash
# PaperDesk 2.0 launcher (macOS / Linux)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "[1/5] creating .venv ..."
  python3 -m venv .venv
  "$PY" -m pip install --upgrade pip
  echo "[2/5] installing requirements ..."
  "$PY" -m pip install -r requirements.txt
else
  echo "[1/5] .venv found"
fi

[ -f .env ] || cp .env.example .env

if [ ! -f config/powercontext.env ]; then
  echo "[3/5] generating PowerContext config ..."
  mkdir -p config
  printf 'y\n' | "$ROOT/.venv/bin/powercontext" config init --template --output config/powercontext.env >/dev/null
fi

export POWERCONTEXT_HOME="$ROOT/runtime/powercontext"
mkdir -p "$POWERCONTEXT_HOME"

if ! curl -sf http://127.0.0.1:18000/health/ready >/dev/null 2>&1; then
  echo "[4/5] starting PowerContext ..."
  set -a
  . config/powercontext.env
  set +a
  nohup "$ROOT/.venv/bin/powercontext" server run --env-file config/powercontext.env --port 18000 \
    >runtime/powercontext.log 2>&1 &
  for _ in $(seq 1 90); do
    curl -sf http://127.0.0.1:18000/health/ready >/dev/null 2>&1 && break
    sleep 1
  done
  curl -sf http://127.0.0.1:18000/health/ready >/dev/null 2>&1 || { echo "PowerContext failed to start"; exit 1; }
else
  echo "[4/5] PowerContext already running"
fi

if [ "${1:-}" != "--skip-seed" ]; then
  echo "[5/5] loading demo corpus ..."
  "$PY" scripts/seed.py
fi

PORT="${PAPERDESK_PORT:-8080}"
echo ""
echo "  PaperDesk    ->  http://127.0.0.1:$PORT"
echo "  PowerContext ->  http://127.0.0.1:18000"
echo ""
exec "$PY" backend/run.py
