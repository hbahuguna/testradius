#!/usr/bin/env bash
# Verify the local toolchain before bootstrap. Fails fast with an actionable message.
set -uo pipefail

status=0
ok() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad() { printf '  \033[31m✗\033[0m %s\n' "$1"; status=1; }

check_cmd() {
  local name="$1"
  shift
  if command -v "$name" >/dev/null 2>&1; then
    ok "$name — $("$@" 2>/dev/null | head -1)"
  else
    bad "$name is not installed"
  fi
}

echo "TestRadius Factory — toolchain"
check_cmd node node --version
check_cmd pnpm pnpm --version
check_cmd uv uv --version
check_cmd docker docker --version
check_cmd curl curl --version

node_major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
if [ "${node_major:-0}" -ge 22 ]; then
  ok "node major ${node_major} satisfies >= 22 (pnpm 11 engine)"
else
  bad "node >= 22 required for pnpm 11 (found ${node_major}); use nvm/asdf with .nvmrc"
fi

if uv python find 3.12 >/dev/null 2>&1; then
  ok "python 3.12 available via uv ($(uv python find 3.12))"
else
  bad "python 3.12 missing; run: uv python install 3.12"
fi

if docker compose version >/dev/null 2>&1; then
  ok "docker compose v2 available"
else
  bad "docker compose v2 is required"
fi

if docker info >/dev/null 2>&1; then
  ok "docker daemon is running"
else
  bad "docker daemon is not running"
fi

if [ "$status" -ne 0 ]; then
  echo
  echo "Fix the items above, then re-run: make doctor"
fi
exit "$status"
