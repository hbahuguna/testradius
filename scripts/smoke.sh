#!/usr/bin/env bash
# Factory smoke: every service answers, the cell is provably non-root, and
# Sprint 2's run lifecycle works locally (the CP dispatch path remains staged
# to S5 — see docs/sprints/sprint-2-plan.md).
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

create="$(curl -sS --max-time 5 -X POST http://localhost:58000/v1/runs \
  -H 'Content-Type: application/json' \
  -d '{"repo":"fixture","commit":"smoke","scope":"full","policy":{"allow_network":false}}' || true)"
run_id="$(printf '%s' "$create" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("run_id",""))' 2>/dev/null || true)"
run_token="$(printf '%s' "$create" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("run_token",""))' 2>/dev/null || true)"
if [ -n "$run_id" ] && [ -n "$run_token" ]; then
  pass "cell POST /v1/runs created $run_id"
else
  fail "cell POST /v1/runs failed: $create"
fi

if [ -n "$run_id" ] && [ -n "$run_token" ]; then
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
    -H "Authorization: Bearer $run_token" "http://localhost:58000/v1/runs/$run_id" || true)"
  if [ "$code" = "200" ]; then pass "cell GET /v1/runs/{id}"; else fail "cell GET run got $code"; fi

  events="$(curl -sS --max-time 5 -H "Authorization: Bearer $run_token" \
    "http://localhost:58000/v1/runs/$run_id/events" || true)"
  if printf '%s' "$events" | grep -q 'run.completed'; then
    pass "cell SSE stream completed all phases"
  else
    fail "cell SSE stream did not reach run.completed"
  fi
fi

echo
if [ "$status" -ne 0 ]; then
  echo "smoke failed"
  exit 1
fi
echo "smoke passed"
