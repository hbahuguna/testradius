#!/usr/bin/env bash
# Run all workbench services locally (outside Docker).
# Starts both the workbench proxy backend and the SDET agent API.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

WORKBENCH_PORT="${WORKBENCH_PORT:-8000}"
SDET_PORT="${SDET_PORT:-8004}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

cleanup() {
  echo ""
  echo "Shutting down..."
  [ -n "${WORKBENCH_PID:-}" ] && kill "$WORKBENCH_PID" 2>/dev/null || true
  [ -n "${SDET_PID:-}" ] && kill "$SDET_PID" 2>/dev/null || true
  [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null || true
  exit 0
}
trap cleanup SIGINT SIGTERM

export PYTHONPATH="$PROJECT_DIR/services/workbench${PYTHONPATH:+:$PYTHONPATH}"

echo "============================================"
echo " TestRadius Workbench - Local Dev"
echo "============================================"
echo ""
echo "Starting services..."

# 1. Workbench proxy backend (main.py)
cd "$PROJECT_DIR/services/workbench"
uv run uvicorn testsquad_workbench.main:app --host 0.0.0.0 --port "$WORKBENCH_PORT" &
WORKBENCH_PID=$!
echo "  Workbench API:  http://localhost:$WORKBENCH_PORT  (PID: $WORKBENCH_PID)"

# 2. SDET agent API (api.py)
uv run uvicorn api:app --host 0.0.0.0 --port "$SDET_PORT" --reload &
SDET_PID=$!
echo "  SDET API:       http://localhost:$SDET_PORT  (PID: $SDET_PID)"

# 3. Frontend Vite dev server
cd "$PROJECT_DIR/apps/workbench"
VITE_WORKBENCH_API="http://localhost:$WORKBENCH_PORT" \
VITE_SDET_API="http://localhost:$SDET_PORT" \
  npx vite --host 0.0.0.0 --port "$FRONTEND_PORT" &
FRONTEND_PID=$!
echo "  Frontend:       http://localhost:$FRONTEND_PORT  (PID: $FRONTEND_PID)"

echo ""
echo "============================================"
echo " All services starting. Press Ctrl+C to stop."
echo "============================================"

wait
