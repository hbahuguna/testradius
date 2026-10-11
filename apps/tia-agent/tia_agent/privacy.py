"""Privacy policy enforcement (E5/P1) — single source of truth.

Two data flows leave the user's machine:

* **LLM provider** (D11): only *changed file paths*, *selected symbol names*,
  aggregate counts/confidence, and the conversation. Never code, diffs, test
  bodies, or file contents.
* **License server** (D12): only summary metadata — an opaque ``repo_hash``,
  counts, language, timing, OS, and the agent version. Never repo names, paths,
  symbol names, test names, or code.

This module is imported by :mod:`tia_agent.license_guard` (license allowlist)
and :mod:`tia_agent.conversation.context` (LLM allowlist). It deliberately has
**no** intra-package imports so it cannot participate in an import cycle.

The human-readable policy lives in
``docs/project/tia-commercial-agent/PRIVACY.md``.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

#: Everything the LLM is ever allowed to see (D11). Mirrors the D11 decision;
#: ``conversation.context`` uses this as its ``ALLOWED_KEYS``.
LLM_CONTEXT_ALLOWED = frozenset({
    "repo",
    "pr_number",
    "changed_files",   # paths only
    "symbols",         # symbol names only
    "tests_selected",
    "total_affected_tests",
    "total_tests_in_repo",
    "fallback_used",
    "fallback_reason",
    "confidence",
    "instrumented",
    "evidence_fresh",
})

#: Everything the license server is ever allowed to receive (D12). The server
#: independently re-applies this allowlist; we also filter client-side.
LICENSE_METADATA_ALLOWED = frozenset({
    "repo_hash",
    "file_count",
    "test_count",
    "language",
    "duration_seconds",
    "os",
    "agent_version",
})


class PrivacyError(RuntimeError):
    """Raised when outbound data violates the D11/D12 contracts."""


def filter_license_metadata(metadata: Mapping[str, Any] | None) -> Dict[str, Any]:
    """Strip everything but the D12 allowlist before it leaves the process."""
    if not metadata:
        return {}
    return {k: v for k, v in metadata.items() if k in LICENSE_METADATA_ALLOWED}


def assert_license_metadata_safe(metadata: Mapping[str, Any] | None) -> None:
    """Raise if any outbound license field is outside the D12 allowlist."""
    for key in metadata or {}:
        if key not in LICENSE_METADATA_ALLOWED:
            raise PrivacyError(f"field '{key}' is not allowed in license metadata (D12)")


def assert_llm_context_safe(context: Mapping[str, Any] | None) -> None:
    """Raise if an outbound LLM context carries anything beyond the D11 allowlist."""
    for key in context or {}:
        if key not in LLM_CONTEXT_ALLOWED:
            raise PrivacyError(f"field '{key}' is not allowed in LLM context (D11)")
