#!/usr/bin/env bash
set -euo pipefail

MODEL_DIR="${SDET_MODEL_PATH:-/Users/skaparwan/Documents/qwen3-8b-sdet}"
PORT="${SDET_PORT:-8003}"
VENV="$MODEL_DIR/.venv"

cd "$(dirname "$0")/../services/workbench"

if [ ! -f "$VENV/bin/python3.11" ]; then
  echo "Creating venv..."
  python3.11 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip setuptools 2>/dev/null
fi

echo "Ensuring deps..."
"$VENV/bin/pip" install --quiet \
  fastapi uvicorn pydantic httpx jinja2 beautifulsoup4 lxml playwright \
  'numpy<2' 'transformers>=4.51.0,<4.52.0' \
  'regex>=2025.10.22' torch accelerate 2>/dev/null || true

export SDET_MODEL_PATH="$MODEL_DIR"
export SDET_BASE_MODEL="$MODEL_DIR"

echo "Starting SDET API on port $PORT"
echo "  model: $MODEL_DIR"
exec "$VENV/bin/uvicorn" api:app \
  --host 0.0.0.0 --port "$PORT"
