#!/usr/bin/env bash
# Wait until every factory service answers its health endpoint.
set -uo pipefail

COMPOSE="docker compose -f infra/compose/compose.factory.yaml --project-name testradius-factory"
DEADLINE=$((SECONDS + 300))

checks=(
  "cell|http://localhost:58000/v1/health"
  "control-plane|http://localhost:58001/healthz"
  "web|http://localhost:53000/healthz"
  "mock-aut|http://localhost:58080/api/health"
  "mock-oidc|http://localhost:58090/healthz"
  "neo4j|http://localhost:57474"
  "minio|http://localhost:59000/minio/health/live"
  "vault|http://localhost:58200/v1/sys/health"
)

all_ready() {
  for spec in "${checks[@]}"; do
    url="${spec#*|}"
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$url" || true)"
    [ "$code" = "200" ] || return 1
  done
  $COMPOSE exec -T postgres pg_isready -U testsquad -d factory >/dev/null 2>&1 || return 1
  return 0
}

printf "waiting for the stack"
while ! all_ready; do
  if [ "$SECONDS" -ge "$DEADLINE" ]; then
    echo
    echo "timed out after ${SECONDS}s. Current state:"
    $COMPOSE ps || true
    exit 1
  fi
  printf "."
  sleep 2
done

echo " ready"
