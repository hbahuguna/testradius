#!/usr/bin/env bash
# Build the standalone tia-agent binary with PyInstaller (E6/R1).
#
#   apps/tia-agent/scripts/build_binary.sh
#   -> dist/tia-agent  (+ SHA256 printed)
#
# Uses a dedicated build venv so it never touches the dev/test venv. Runs the
# smoke checks in a stripped environment (env -i) to approximate a clean machine.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$here"

build_venv="$here/.venv-build"
mkdir -p dist

echo "==> Setting up build venv ($build_venv)"
uv venv "$build_venv" --python 3.12 --allow-existing >/dev/null
uv pip install --python "$build_venv/bin/python" -e ".[build]" >/dev/null

echo "==> Building one-file binary (PyInstaller)"
"$build_venv/bin/pyinstaller" --noconfirm --clean tia-agent.spec

binary="$here/dist/tia-agent"
test -x "$binary" || { echo "ERROR: $binary not produced" >&2; exit 1; }

echo "==> Smoke test on a stripped environment (env -i PATH=/usr/bin:/bin)"
env -i PATH=/usr/bin:/bin HOME="$HOME" "$binary" --version
env -i PATH=/usr/bin:/bin HOME="$HOME" "$binary" --help >/dev/null

echo "==> Artifact"
ls -lh "$binary"
if command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$binary"
else
  sha256sum "$binary"
fi
