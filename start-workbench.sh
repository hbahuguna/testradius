#!/usr/bin/env bash
# Boot the full SDET workbench stack for manual UI testing:
#   1. SDET agent backend      -> http://localhost:8006  (/v1/execute, /v1/heal)
#   2. Workbench API (proxy)   -> http://localhost:8004  (/api/workbench/*)
#   3. Workbench UI (Vite)     -> http://localhost:5174  (open this in a browser)
#
# Usage:
#   ./start-workbench.sh            # uses existing env for OPENCODE_API_KEY
#   OPENCODE_API_KEY=sk-... ./start-workbench.sh
#
# Press Ctrl-C to stop everything.

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDET_VENV="$ROOT/apps/sdet-agent/.venv/bin/python"
WB_VENV="$ROOT/services/workbench/.venv/bin/python"
UI_DIR="$ROOT/apps/workbench"
LOG_DIR="/tmp/workbench-logs"
mkdir -p "$LOG_DIR"

# --- load env (so OPENCODE_API_KEY + browser cache reach the servers) --------
# Source a local .env (gitignored) if present; this is the recommended way to
# persist the key across restarts. Variables already exported in the parent
# shell take precedence.
if [ -f "$ROOT/.env" ]; then
  set -a
  . "$ROOT/.env"
  set +a
fi
export OPENCODE_API_KEY="${OPENCODE_API_KEY:-}"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/Library/Caches/ms-playwright}"

if [ -z "${OPENCODE_API_KEY:-}" ]; then
  echo "ERROR: OPENCODE_API_KEY is not set. The agentic healer/generator (hy3-free)"
  echo "       cannot call OpenCode Zen without it -- every run/heal would fail."
  echo "       Fix: create $ROOT/.env with 'OPENCODE_API_KEY=sk-...'"
  echo "       or run 'export OPENCODE_API_KEY=sk-...' before this script."
  exit 1
fi
[ -x "$SDET_VENV" ] || { echo "MISSING: $SDET_VENV"; exit 1; }
[ -x "$WB_VENV" ]   || { echo "MISSING: $WB_VENV"; exit 1; }
[ -d "$UI_DIR/node_modules" ] || { echo "MISSING: $UI_DIR/node_modules (run 'npm install' in apps/workbench)"; exit 1; }

PIDS=()
cleanup() {
  echo ""
  echo "Shutting down workbench stack..."
  [ -n "${TAIL_PID:-}" ] && kill "$TAIL_PID" 2>/dev/null
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null
  done
  wait 2>/dev/null
  echo "Done."
}
trap cleanup INT TERM

# --- 1. SDET agent backend (:8006) ------------------------------------------
echo "[1/3] Starting SDET agent backend on :8006 ..."
(
  cd "$ROOT/apps/sdet-agent"
  exec "$SDET_VENV" -m uvicorn sdet_agent.interfaces.http_server:app \
    --host 0.0.0.0 --port 8006 --log-level info
) >> "$LOG_DIR/sdet-agent.log" 2>&1 &
PIDS+=($!)

# --- 2. Workbench API proxy (:8004) ----------------------------------------
echo "[2/3] Starting workbench API on :8004 (proxies to :8006) ..."
(
  cd "$ROOT/services/workbench"
  export SDET_AGENT_API="${SDET_AGENT_API:-http://localhost:8006}"
  exec "$WB_VENV" -m uvicorn api:app \
    --host 0.0.0.0 --port 8004 --log-level info
) >> "$LOG_DIR/workbench-api.log" 2>&1 &
PIDS+=($!)

# --- 3. Workbench UI (Vite dev server :5174) -------------------------------
echo "[3/3] Starting workbench UI (Vite) on :5174 ..."
(
  cd "$UI_DIR"
  export VITE_SDET_API="${VITE_SDET_API:-http://localhost:8004}"
  exec npm run dev:vite
) >> "$LOG_DIR/workbench-ui.log" 2>&1 &
PIDS+=($!)

# --- health check -----------------------------------------------------------
echo "Waiting for services to come up..."
for i in $(seq 1 30); do
  if curl -s -o /dev/null -m 2 http://localhost:8006/health && \
     curl -s -o /dev/null -m 2 http://localhost:8004/api/workbench/health; then
    echo "Backend (:8006) and API (:8004) are up."
    break
  fi
  sleep 1
done

echo ""
echo "==================================================================="
echo " Workbench stack running."
echo "   SDET agent backend : http://localhost:8006  (logs: $LOG_DIR/sdet-agent.log)"
echo "   Workbench API      : http://localhost:8004  (logs: $LOG_DIR/workbench-api.log)"
echo "   Workbench UI       : http://localhost:5174  (logs: $LOG_DIR/workbench-ui.log)"
echo ""
echo " Open http://localhost:5174 in your browser, enter a URL, click Go,"
echo " then use the 'Agentic' tab to run a goal-driven test."
echo ""
echo " Ctrl-C to stop all three processes."
echo "==================================================================="

# --- tail UI log so Ctrl-C is the natural exit -----------------------------
tail -f "$LOG_DIR/workbench-ui.log" &
TAIL_PID=$!
wait $TAIL_PID
