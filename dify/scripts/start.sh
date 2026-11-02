#!/usr/bin/env bash
# Moonfall local services (Linux / macOS / WSL)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DATA_DIR="${POWERCONTEXT_DATA_DIR:-$HOME/.local/share/moonfall/powercontext}"
export POWERCONTEXT_DATA_DIR="$DATA_DIR"
export PYTHONIOENCODING=utf-8
mkdir -p logs

if [ ! -d .venv ]; then
  echo "[1/4] creating .venv"
  python3 -m venv .venv
fi
PYTHON="$ROOT/.venv/bin/python"

echo "[2/4] installing dependencies (first run: 1-3 minutes)"
"$PYTHON" -m pip install --upgrade pip --quiet
"$PYTHON" -m pip install -r requirements.txt --quiet

wait_http() {
  local url="$1"
  local seconds="${2:-120}"
  local deadline=$((SECONDS + seconds))
  while [ $SECONDS -lt $deadline ]; do
    if curl -fsS "$url" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  return 1
}

echo "[3/4] starting PowerContext on 8099"
nohup "$PYTHON" scripts/run_powercontext.py --host 0.0.0.0 --port 8099 > logs/powercontext.log 2>&1 &
echo $! > logs/powercontext.pid
if ! wait_http "http://127.0.0.1:8099/health/ready" 180; then
  echo "PowerContext failed; see logs/powercontext.log" >&2
  exit 1
fi

echo "[4/4] starting narrator shim on 8101 (optional offline model)"
nohup "$PYTHON" tools/openai_shim.py --host 0.0.0.0 --port 8101 > logs/shim.log 2>&1 &
echo $! > logs/shim.pid
wait_http "http://127.0.0.1:8101/health" 30 || echo "WARN: shim failed; use a real model"

cat > logs/pids.json <<EOF
{"powercontext": $(cat logs/powercontext.pid), "shim": $(cat logs/shim.pid), "data_dir": "$DATA_DIR"}
EOF

echo ""
echo "  PowerContext -> http://127.0.0.1:8099"
echo "  narrator     -> http://127.0.0.1:8101/v1 (model=moonfall-narrator)"
echo "  data dir     -> $DATA_DIR"
echo ""
echo "Next: import dsl/moonfall-werewolf.chatflow.yml into Dify 1.17.0."
echo "Set POWERCONTEXT_BASE to http://host.docker.internal:8099 (Docker) or http://127.0.0.1:8099 (native)."
echo "Stop: bash scripts/stop.sh"
