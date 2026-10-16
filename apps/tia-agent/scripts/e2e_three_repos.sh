#!/usr/bin/env bash
# E7 live three-repo E2E: py-key-value + Test-Radius + psf/requests.
#
# Requires a running TestRadius backend with the three projects and their
# instrumentation evidence already built. Pass --instrument to build evidence
# for any project that is missing it (slow: clones + runs real test suites).
#
# Usage:
#   scripts/e2e_three_repos.sh [--radius-url URL] [--quota N] [--instrument]
set -euo pipefail

cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"
RADIUS_URL="${TIA_RADIUS_URL:-http://localhost:8000}"

if ! curl -sf -m 5 "$RADIUS_URL/health" >/dev/null; then
  echo "TestRadius backend not reachable at $RADIUS_URL" >&2
  echo "Start it with: docker compose --profile ml up -d" >&2
  exit 2
fi

env -u TIA_RADIUS_URL -u TIA_RADIUS_TOKEN -u TIA_LICENSE_URL \
    -u TIA_CONFIG_HOME -u TIA_LICENSE_STATE_PATH -u TIA_GITHUB_TOKEN \
    PYTHONPATH=. "$PY" scripts/e2e_three_repos.py --radius-url "$RADIUS_URL" "$@"
