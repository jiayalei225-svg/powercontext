#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ ! -x ".venv/bin/python" ]; then
  echo "[1/3] Creating virtual environment..."
  "$PYTHON_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "[2/3] Installing dependencies..."
python -m pip install --disable-pip-version-check -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "[i] Created .env from .env.example"
fi

echo "[3/3] Starting http://127.0.0.1:8090"
exec python -m uvicorn app.main:app --host 127.0.0.1 --port 8090
