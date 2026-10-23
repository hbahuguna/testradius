#!/usr/bin/env bash
# Seed dev-only secrets into the local Vault. Values are generated here and are
# never written to disk or printed (E0-S8).
set -uo pipefail

VAULT_ADDR="${VAULT_ADDR:-http://localhost:58200}"
VAULT_TOKEN="${VAULT_TOKEN:-dev-root-token}"

if ! curl -fsS -H "X-Vault-Token: ${VAULT_TOKEN}" "${VAULT_ADDR}/v1/sys/health" >/dev/null 2>&1; then
  echo "vault is not reachable at ${VAULT_ADDR}; run 'make up' first" >&2
  exit 1
fi

gen() { openssl rand -hex 24; }

put() {
  local path="$1" value="$2"
  curl -fsS -H "X-Vault-Token: ${VAULT_TOKEN}" \
    -H "Content-Type: application/json" \
    -X POST "${VAULT_ADDR}/v1/secret/data/${path}" \
    -d "{\"data\":{\"value\":\"${value}\"}}" >/dev/null
}

put "factory/llm" "$(gen)"
put "factory/github" "$(gen)"
put "factory/db" "$(gen)"
put "factory/evidence" "$(gen)"

echo "seeded dev secrets (values not printed):"
echo "  secret/factory/llm"
echo "  secret/factory/github"
echo "  secret/factory/db"
echo "  secret/factory/evidence"
