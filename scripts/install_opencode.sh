#!/usr/bin/env bash
# Install OpenCode (a Node CLI) so the testradius session server (port 9800)
# can spawn it. OpenCode must be on PATH for the Python OpenCodeBridge, which
# execs `opencode` (or $OPENCODE_BIN). This script is idempotent and is meant
# to run BEFORE `testradius serve` / before the SDET workbench uses OpenCode.
#
# Usage: bash scripts/install_opencode.sh
set -euo pipefail

BIN="opencode"

if command -v "$BIN" >/dev/null 2>&1; then
  echo "OpenCode already installed: $(command -v "$BIN")"
  "$BIN" --version 2>/dev/null || true
  exit 0
fi

echo "OpenCode not found on PATH. Installing..."

if ! command -v npm >/dev/null 2>&1; then
  echo "ERROR: npm is required to install OpenCode. Install Node.js (https://nodejs.org) and retry." >&2
  exit 1
fi

if ! npm install -g opencode; then
  echo "ERROR: 'npm install -g opencode' failed." >&2
  echo "See https://opencode.ai for the official installer, then re-run this script." >&2
  exit 1
fi

# Make the global npm bin dir available in this session (non-interactive shells
# may not have it on PATH yet).
NPM_PREFIX="$(npm config get prefix)"
NPM_BIN="$NPM_PREFIX/bin"
case ":$PATH:" in
  *":$NPM_BIN:"*) ;;
  *) export PATH="$NPM_BIN:$PATH" ;;
esac

if command -v "$BIN" >/dev/null 2>&1; then
  echo "OpenCode installed: $(command -v "$BIN")"
  "$BIN" --version 2>/dev/null || true
else
  echo "WARNING: OpenCode installed globally but not detected on PATH." >&2
  echo "Add the npm global bin dir to your shell profile:" >&2
  echo "  export PATH=\"$NPM_BIN:\$PATH\"" >&2
  exit 1
fi
