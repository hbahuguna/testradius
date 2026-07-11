#!/usr/bin/env bash
# Run all workbench services locally (outside Docker).
# Starts both the workbench proxy backend and the SDET agent API.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

WORKBENCH_PORT="${WORKBENCH_PORT:-8000}"
SDET_PORT="${SDET_PORT:-8004}"
SDET_AGENT_PORT="${SDET_AGENT_PORT:-8006}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

# The workbench API (SDET Port) proxies test generation to the standalone
# sdet-agent service. Point it at the agent service started below.
export SDET_AGENT_API="${SDET_AGENT_API:-http://localhost:$SDET_AGENT_PORT}"

# OpenCode Zen API key for the hy3-free model used by the sdet-agent's
# LLM path (falls back to rule-based generation if unset). Prefer exporting
# this from your shell or a non-committed .env over hardcoding; if already
# set in the environment it takes precedence.
export OPENCODE_API_KEY="${OPENCODE_API_KEY:-sk-fC0fEkAB10vctVpV4d2wUJp5wWLkSB23jZKVx9aeBMmHN22o7OYg1HQ7Z7ZwraV5}"

cleanup() {
  echo ""
  echo "Shutting down..."
  [ -n "${WORKBENCH_PID:-}" ] && kill "$WORKBENCH_PID" 2>/dev/null || true
  [ -n "${SDET_PID:-}" ] && kill "$SDET_PID" 2>/dev/null || true
  [ -n "${SDET_AGENT_PID:-}" ] && kill "$SDET_AGENT_PID" 2>/dev/null || true
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

# 2. SDET agent API (api.py) — orchestrates sessions + streams sdet-agent output
uv run uvicorn api:app --host 0.0.0.0 --port "$SDET_PORT" --reload &
SDET_PID=$!
echo "  SDET API:       http://localhost:$SDET_PORT  (PID: $SDET_PID)"

# 2b. Standalone SDET-agent service (apps/sdet-agent) — generates the test code
bash "$SCRIPT_DIR/start-sdet-agent.sh" &
SDET_AGENT_PID=$!
echo "  SDET Agent:     http://localhost:$SDET_AGENT_PORT  (PID: $SDET_AGENT_PID)"

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
