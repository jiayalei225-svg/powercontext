#!/usr/bin/env bash
# Start the project-owned PowerContext instance.
#
# It listens on 8010 (not the default 8000) and asks StudyCoach for embeddings
# through POST /v1/embeddings, so memory search uses the same local BGE model
# as the document index and no external embedding key is needed.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x ".venv/bin/powercontext" ]; then
  echo "PowerContext is not installed yet. Run scripts/start_macos.sh first."
  exit 1
fi

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

export POWERCONTEXT_HOME="${POWERCONTEXT_HOME:-$PWD/data/powercontext}"
export POWERCONTEXT_SERVER_HTTP_HOST="${POWERCONTEXT_HOST:-127.0.0.1}"
export POWERCONTEXT_SERVER_HTTP_PORT="${POWERCONTEXT_PORT:-8010}"
export POWERCONTEXT_SERVER_LOGGING_LEVEL="${POWERCONTEXT_LOG_LEVEL:-INFO}"
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_MODEL="openai:${EMBEDDING_MODEL:-bge-small-zh-v1.5}"
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_BASE_URL="${POWERCONTEXT_EMBEDDING_BASE_URL:-http://127.0.0.1:${APP_PORT:-8090}/v1}"
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_PROFILE_ID="${EMBEDDING_MODEL:-bge-small-zh-v1.5}"
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_DIMENSION="${EMBEDDING_DIM:-512}"

mkdir -p "$POWERCONTEXT_HOME"

echo "PowerContext starting on http://${POWERCONTEXT_SERVER_HTTP_HOST}:${POWERCONTEXT_SERVER_HTTP_PORT}"
echo "Embedding provider: $POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_BASE_URL"
exec .venv/bin/powercontext server run --no-env-file
