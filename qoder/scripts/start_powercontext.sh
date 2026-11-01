#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x ".venv/bin/powercontext" ]; then
  echo "PowerContext is not installed yet. Run start_macos.sh first."
  exit 1
fi

export POWERCONTEXT_HOME="$PWD/data/powercontext"
mkdir -p "$POWERCONTEXT_HOME"

echo "PowerContext starting on http://127.0.0.1:8000"
exec .venv/bin/powercontext server run
