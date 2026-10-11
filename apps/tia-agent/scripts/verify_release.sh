#!/usr/bin/env bash
# Verify a published tia-agent GitHub Release (E6/R2).
#
#   apps/tia-agent/scripts/verify_release.sh 0.1.0
#   apps/tia-agent/scripts/verify_release.sh 0.1.0 --repo OWNER/REPO
#   apps/tia-agent/scripts/verify_release.sh 0.1.0 --key cosign.pub
#   apps/tia-agent/scripts/verify_release.sh 0.1.0 --certificate-identity-regexp '...'
#
# Downloads the release assets, checks SHA256SUMS, then verifies each signature
# with cosign. Defaults to keyless verification (GitHub Actions OIDC identity);
# pass --key to verify with a public key instead.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$here"

version="${1:-}"
if [ -z "$version" ]; then
  echo "usage: $0 <version> [--repo OWNER/REPO] [--key FILE] [--certificate-identity-regexp RE]" >&2
  exit 2
fi
shift || true

tag="tia-agent-v$version"
repo=""
key=""
identity_re=""
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) repo="${2:?}"; shift 2 ;;
    --key) key="${2:?}"; shift 2 ;;
    --certificate-identity-regexp) identity_re="${2:?}"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

command -v gh >/dev/null 2>&1 || { echo "ERROR: gh not found on PATH" >&2; exit 1; }
command -v cosign >/dev/null 2>&1 || { echo "ERROR: cosign not found on PATH" >&2; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "==> Downloading release $tag"
gh release download "$tag" ${repo:+--repo "$repo"} --dir "$work"
( cd "$work" && ls -lh )

echo "==> Verifying SHA256SUMS"
.venv-build/bin/python -m tia_agent.release verify -c "$work/SHA256SUMS" -d "$work"

echo "==> Verifying cosign signatures"
shopt -s nullglob
for f in "$work"/tia-agent-* "$work"/SHA256SUMS; do
  case "$f" in *.sigstore.json) continue;; esac
  bundle="$f.sigstore.json"
  if [ -n "$key" ]; then
    cosign verify-blob --key "$key" --bundle "$bundle" "$f"
  else
    args=(--bundle "$bundle"
          --certificate-oidc-issuer https://token.actions.githubusercontent.com)
    if [ -n "$identity_re" ]; then
      args+=(--certificate-identity-regexp "$identity_re")
    fi
    cosign verify-blob "${args[@]}" "$f"
  fi
done

echo "OK: release $tag verified"
