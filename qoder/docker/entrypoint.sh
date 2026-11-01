#!/usr/bin/env sh
# Container entrypoint: app first, then PowerContext.
#
# PowerContext probes POST /v1/embeddings during startup and caches the result.
# If it starts before the app is listening, memory stays "degraded" even after
# the app comes up. This is the same ordering the Windows/macOS scripts use.
set -eu

APP_PORT="${APP_PORT:-8090}"
MODEL="${EMBEDDING_MODEL:-bge-small-zh-v1.5}"
DIM="${EMBEDDING_DIM:-512}"
DATA_DIR="${DATA_DIR:-/data}"

export APP_HOST="${APP_HOST:-0.0.0.0}"
export DATA_DIR
export SEEKDB_PATH="${SEEKDB_PATH:-$DATA_DIR/seekdb}"
export MODEL_DIR="${MODEL_DIR:-$DATA_DIR/models}"
export USER_ID="${USER_ID:-local}"

mkdir -p "$DATA_DIR" "$SEEKDB_PATH" "$MODEL_DIR"

PC_PID=""
cleanup() {
  if [ -n "$PC_PID" ]; then kill "$PC_PID" 2>/dev/null || true; fi
  kill "$APP_PID" 2>/dev/null || true
}
trap cleanup INT TERM

echo "[1/2] Starting StudyCoach on 0.0.0.0:${APP_PORT}"
python -m app.run &
APP_PID=$!

i=0
while ! curl -fsS "http://127.0.0.1:${APP_PORT}/health" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 240 ]; then
    echo "[x] StudyCoach did not become healthy; see the container logs above."
    exit 1
  fi
  sleep 0.5
done
echo "[i] StudyCoach is healthy; starting PowerContext"

export POWERCONTEXT_HOME="${POWERCONTEXT_HOME:-$DATA_DIR/powercontext}"
export POWERCONTEXT_SERVER_HTTP_HOST=0.0.0.0
export POWERCONTEXT_SERVER_HTTP_PORT="${POWERCONTEXT_PORT:-8010}"
export POWERCONTEXT_SERVER_LOGGING_LEVEL="${POWERCONTEXT_LOG_LEVEL:-INFO}"
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_MODEL="openai:${MODEL}"
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_BASE_URL="${POWERCONTEXT_EMBEDDING_BASE_URL:-http://127.0.0.1:${APP_PORT}/v1}"
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_PROFILE_ID="$MODEL"
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_DIMENSION="$DIM"

mkdir -p "$POWERCONTEXT_HOME"
echo "[2/2] Starting PowerContext on 0.0.0.0:${POWERCONTEXT_SERVER_HTTP_PORT}"
powercontext server run --no-env-file &
PC_PID=$!

wait "$PC_PID"
