#!/usr/bin/env bash
# Run the SDET workbench backend locally (outside Docker) with the Qwen3 model.
# Requires: transformers>=4.51.0, torch, uvicorn
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

export PYTHONPATH="$PROJECT_DIR/services/workbench:$PROJECT_DIR/packages/shared${PYTHONPATH:+:$PYTHONPATH}"
export SDET_MODEL_PATH="${SDET_MODEL_PATH:-/Users/skaparwan/Documents/qwen3-8b-sdet}"
export SDET_BASE_MODEL="${SDET_BASE_MODEL:-Qwen/Qwen3-8B}"
export SDET_PORT="${SDET_PORT:-8004}"

cd "$PROJECT_DIR/services/workbench"

# Best-effort: ensure OpenCode CLI is installed (needed by the 'testradius serve'
# OpenCode path). The SDET API itself falls back to Qwen if it's missing.
bash "$SCRIPT_DIR/install_opencode.sh" || \
  echo "WARN: OpenCode not installed (only required for the OpenCode generation path)."

echo "SDET Model: $SDET_MODEL_PATH"
echo "SDET API: http://localhost:$SDET_PORT"
echo "Frontend VITE_SDET_API: http://localhost:$SDET_PORT"
echo ""

exec uvicorn api:app --host 0.0.0.0 --port "$SDET_PORT" --reload
