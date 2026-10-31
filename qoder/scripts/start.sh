#!/usr/bin/env bash
# PaperDesk 启动脚本（macOS / Linux / WSL）
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -d .venv ]; then
  echo "[1/4] 创建虚拟环境并安装依赖（首次约 3-5 分钟）"
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
else
  echo "[1/4] 已存在 .venv，跳过安装"
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "[3/4] 已从 .env.example 生成 .env"
fi

if [ ! -f config/powercontext.env ]; then
  echo "生成 PowerContext 配置"
  echo y | .venv/bin/powercontext config init --template --output config/powercontext.env >/dev/null
fi

echo "[4/4] 启动 PowerContext（记忆服务）"
set -a
# shellcheck disable=SC1091
. config/powercontext.env
set +a
.venv/bin/powercontext server run > powercontext.log 2>&1 &
PC_PID=$!

for _ in $(seq 1 60); do
  if curl -sf http://127.0.0.1:8000/health/ready >/dev/null; then break; fi
  sleep 1
done

PORT="${PAPERDESK_PORT:-8080}"
echo ""
echo "  PaperDesk   ->  http://127.0.0.1:${PORT}"
echo "  PowerContext->  http://127.0.0.1:8000  (PID $PC_PID)"
echo "  首次使用请另开终端执行：.venv/bin/python scripts/seed.py"
echo ""

trap 'kill $PC_PID 2>/dev/null || true' EXIT
.venv/bin/python backend/run.py
