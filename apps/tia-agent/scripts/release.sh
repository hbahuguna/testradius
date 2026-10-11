#!/usr/bin/env bash
# Build + package + (optionally) sign a tia-agent release from a local machine (E6/R2).
#
#   apps/tia-agent/scripts/release.sh 0.1.0
#   apps/tia-agent/scripts/release.sh 0.1.0 --sign-key cosign.key
#   apps/tia-agent/scripts/release.sh 0.1.0 --sign-key cosign.key --publish
#
# Produces, in dist/:
#   tia-agent-<version>-<os>-<arch>          the binary
#   SHA256SUMS                               sha256sum-compatible checksums
#   <binary>.sigstore.json                   cosign signature bundle
#   SHA256SUMS.sigstore.json                 cosign signature bundle
#
# Only the host OS/arch is built locally (PyInstaller cannot cross-compile);
# the GitHub Actions workflow builds the full macOS+Linux matrix.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$here"

version="${1:-}"
if [ -z "$version" ]; then
  echo "usage: $0 <version> [--sign-key FILE | --keyless] [--publish] [--repo OWNER/REPO]" >&2
  exit 2
fi
shift || true

sign_key=""
keyless=0
publish=0
repo=""
while [ $# -gt 0 ]; do
  case "$1" in
    --sign-key) sign_key="${2:?--sign-key needs a file}"; shift 2 ;;
    --keyless) keyless=1; shift ;;
    --publish) publish=1; shift ;;
    --repo) repo="${2:?--repo needs OWNER/REPO}"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

tag="tia-agent-v$version"

echo "==> Building binary"
./scripts/build_binary.sh

echo "==> Naming artifact"
name="$(.venv-build/bin/python -m tia_agent.release name --version "$version")"
mv -f dist/tia-agent "dist/$name"
echo "    $name"

echo "==> Checksums"
.venv-build/bin/python -m tia_agent.release checksums -o dist/SHA256SUMS "dist/$name"
cat "dist/SHA256SUMS"

sign=0
if [ -n "$sign_key" ]; then
  sign=1
elif [ "$keyless" = "1" ]; then
  sign=2
fi

if [ "$sign" != "0" ]; then
  command -v cosign >/dev/null 2>&1 || { echo "ERROR: cosign not found on PATH" >&2; exit 1; }
  echo "==> Signing with cosign ($([ "$sign" = 1 ] && echo key:id || echo keyless))"
  for f in "dist/$name" dist/SHA256SUMS; do
    if [ "$sign" = "1" ]; then
      cosign sign-blob --yes --key "$sign_key" --bundle "$f.sigstore.json" "$f"
    else
      cosign sign-blob --yes --bundle "$f.sigstore.json" "$f"
    fi
  done
else
  echo "==> Skipping signing (pass --sign-key FILE or --keyless to sign)"
fi

echo "==> Verifying checksums"
.venv-build/bin/python -m tia_agent.release verify -c dist/SHA256SUMS -d dist

echo "==> Verifying signatures"
if [ "$sign" = "1" ]; then
  for f in "dist/$name" dist/SHA256SUMS; do
    cosign verify-blob --key "${sign_key%.key}.pub" --bundle "$f.sigstore.json" "$f"
  done
elif [ "$sign" = "2" ]; then
  echo "    (keyless: skipped locally — needs OIDC; CI verifies before publishing)"
fi

echo "==> Artifacts"
ls -lh dist/

if [ "$publish" = "1" ]; then
  command -v gh >/dev/null 2>&1 || { echo "ERROR: gh not found on PATH" >&2; exit 1; }
  echo "==> Publishing GitHub Release $tag"
  assets=(dist/"$name" dist/SHA256SUMS)
  shopt -s nullglob
  for f in dist/*.sigstore.json; do assets+=("$f"); done
  shopt -u nullglob
  gh release create "$tag" \
    --title "tia-agent $version" \
    --generate-notes \
    ${repo:+--repo "$repo"} \
    "${assets[@]}"
else
  echo "==> Not publishing (pass --publish to create the GitHub Release)"
fi
