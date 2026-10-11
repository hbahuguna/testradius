"""A2 guard: no provider keys may be bundled in the shipped artifact.

This is the pytest form of a `strings <artifact> | grep ...` scan. The same
scanner runs against the frozen binary in R1/R2 — pass the binary path.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "tia_agent"

# Real-world key shapes (openai/anthropic/google/github/slack).
KEY_PATTERNS = [
    re.compile(rb"sk-[A-Za-z0-9]{20,}"),                    # openai
    re.compile(rb"sk-ant-[A-Za-z0-9_\-]{16,}"),             # anthropic
    re.compile(rb"AIza[0-9A-Za-z_\-]{30,}"),                # google api key
    re.compile(rb"ghp_[A-Za-z0-9]{30,}"),                   # github pat
    re.compile(rb"github_pat_[A-Za-z0-9_]{30,}"),
    re.compile(rb"xox[baprs]-[A-Za-z0-9\-]{10,}"),          # slack
    # A literal assigned to a key-ish name, e.g. api_key = "…20+ chars…"
    re.compile(rb"(?i)(?:api[_-]?key|secret|token)\s*[:=]\s*[\"'][A-Za-z0-9_\-]{20,}[\"']"),
]


def scan_bytes_for_keys(data: bytes) -> list[str]:
    hits = []
    for pat in KEY_PATTERNS:
        for m in pat.finditer(data):
            hits.append(m.group().decode("latin-1"))
    return hits


def scan_path_for_keys(path: Path) -> dict[str, list[str]]:
    """Works on source files and on compiled/frozen binaries alike."""
    findings: dict[str, list[str]] = {}
    files = [path] if path.is_file() else sorted(path.rglob("*"))
    for f in files:
        if not f.is_file():
            continue
        data = f.read_bytes()
        hits = scan_bytes_for_keys(data)
        if hits:
            findings[str(f)] = hits
    return findings


def test_package_sources_contain_no_keys():
    findings = scan_path_for_keys(PACKAGE_DIR)
    assert findings == {}, f"possible keys found in package: {findings}"


def test_scanner_actually_detects_a_planted_key(tmp_path):
    """The scan must be able to fail — otherwise it proves nothing."""
    planted = tmp_path / "leak.py"
    planted.write_text('KEY = "sk-abcdefghijklmnopqrstuvwxyz012345"')
    assert scan_path_for_keys(tmp_path)


def test_env_key_names_are_not_secrets():
    """Env-var names are fine; they must just never carry a default value."""
    from tia_agent.llm import ENV_KEYS

    for name in ENV_KEYS.values():
        if name:
            assert "KEY" in name  # a name, not a value
            assert len(name) < 40