#!/usr/bin/env bash
# Stop Moonfall local services started by scripts/start.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
for name in powercontext shim; do
  file="logs/${name}.pid"
  if [ -f "$file" ]; then
    pid="$(cat "$file")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      echo "Stopped $name (PID $pid)"
    fi
    rm -f "$file"
  fi
done
rm -f logs/pids.json
