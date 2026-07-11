#!/usr/bin/env bash
# Launch the standalone SDET-agent service (apps/sdet-agent) used by the
# workbench to generate Playwright tests. Runs in its own venv so it can pull
# in dependencies (beautifulsoup4, tree-sitter, ...) that the workbench API
# venv does not have. Streams OpenCode-style events over /v1/run-stream.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PORT="${SDET_AGENT_PORT:-8006}"
VENV="${SDET_AGENT_VENV:-$PROJECT_DIR/apps/sdet-agent/.venv}"

if [ ! -d "$VENV" ]; then
  echo "Creating sdet-agent venv at $VENV"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
fi

echo "Ensuring sdet-agent deps..."
"$VENV/bin/pip" install --quiet \
  "httpx>=0.28" "pydantic>=2.12" "fastapi>=0.135" "uvicorn[standard]>=0.41" \
  "beautifulsoup4" "tree-sitter>=0.21" "tree-sitter-typescript>=0.21" || true

# Wire OpenCode Zen API key for the hy3-free model if not already set.
if [ -z "${OPENCODE_API_KEY:-}" ] && [ -f "$HOME/.local/share/opencode/auth.json" ]; then
  KEY="$(python3 - "$HOME/.local/share/opencode/auth.json" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(d.get("opencode", "") or d.get("OPENCODE_API_KEY", "") or "")
except Exception:
    pass
PY
)"
  if [ -n "$KEY" ]; then
    export OPENCODE_API_KEY="$KEY"
    echo "Using OPENCODE_API_KEY from ~/.local/share/opencode/auth.json"
  fi
fi

export PYTHONPATH="$PROJECT_DIR/apps/sdet-agent${PYTHONPATH:+:$PYTHONPATH}"
cd "$PROJECT_DIR/apps/sdet-agent"

echo "Starting SDET agent service on port $PORT"
exec "$VENV/bin/uvicorn" sdet_agent.interfaces.http_server:app \
  --host 0.0.0.0 --port "$PORT" --reload
