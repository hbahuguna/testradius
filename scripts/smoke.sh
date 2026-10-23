#!/usr/bin/env bash
# Sprint 1 smoke: every service answers, and the cell is provably non-root.
#
# SMOKE-RUN (run creation through the control plane) is staged to S2/S5 — see
# docs/sprints/sprint-1-plan.md §Staged verification.
set -uo pipefail

COMPOSE="docker compose -f infra/compose/compose.factory.yaml --project-name testradius-factory"
status=0

pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; status=1; }

check_http() {
  local name="$1" url="$2" expect="${3:-200}"
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" || true)"
  if [ "$code" = "$expect" ]; then pass "$name ($code)"; else fail "$name (got ${code:-none}, want $expect)"; fi
}

echo "TestRadius Factory — smoke"
check_http "cell /v1/health" "http://localhost:58000/v1/health"
check_http "control-plane /healthz" "http://localhost:58001/healthz"
check_http "web /healthz" "http://localhost:53000/healthz"
check_http "fixture AUT /api/health" "http://localhost:58080/api/health"
check_http "mock OIDC /healthz" "http://localhost:58090/healthz"
check_http "minio /minio/health/live" "http://localhost:59000/minio/health/live"
check_http "vault /v1/sys/health" "http://localhost:58200/v1/sys/health"
check_http "neo4j browser" "http://localhost:57474"

if $COMPOSE exec -T postgres pg_isready -U testsquad -d factory >/dev/null 2>&1; then
  pass "postgres accepts connections"
else
  fail "postgres is not accepting connections"
fi

if [ "$($COMPOSE exec -T cell id -u 2>/dev/null | tr -d '[:space:]')" = "10001" ]; then
  pass "cell runs as uid 10001"
else
  fail "cell is not running as uid 10001"
fi

if $COMPOSE exec -T cell sh -c 'touch /app/should-fail' >/dev/null 2>&1; then
  fail "cell root filesystem is writable"
else
  pass "cell root filesystem is read-only"
fi

echo
if [ "$status" -ne 0 ]; then
  echo "smoke failed"
  exit 1
fi
echo "smoke passed"
