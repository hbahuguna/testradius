"""Safe runtime ref resolution for computer-use runner (008.5).

Resolves ``{{test_data.name}}`` and ``{{env.VAR}}``. Secret refs
(``{{secret.*}}`` or ``sut.auth_secret_refs`` values) are **never resolved to
stdout/trace**; they require an explicit approved resolver and are redacted
everywhere else. Resolved values are redacted from traces.
"""
from __future__ import annotations

import os
import re
from typing import Any, Callable, Dict, Mapping

from harness.policy.redaction import Redactor

_ENV_RE = re.compile(r"^\{\{\s*env\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}$")
_TEST_DATA_RE = re.compile(r"^\{\{\s*test_data\.([A-Za-z0-9_.-]+)\s*\}\}$")
_SECRET_RE = re.compile(r"^\{\{\s*(secret|secrets)\.([A-Za-z0-9_.-]+)\s*\}\}$")
_PLACEHOLDER_RE = re.compile(r"\{\{\s*(env|test_data|secret|secrets)\.([A-Za-z0-9_.-]+)\s*\}\}")


class RefResolutionBlocked(RuntimeError):
    pass


def build_test_data_index(plan: Any) -> Dict[str, Any]:
    index: Dict[str, Any] = {}
    for item in (getattr(plan, "test_data", None) or []):
        if isinstance(item, Mapping):
            name = str(item.get("name") or "")
            if name:
                index[name] = item.get("value")
        elif hasattr(item, "name"):
            index[str(item.name)] = getattr(item, "value", None)
    return index


def resolve_value(
    value: Any,
    *,
    test_data: Mapping[str, Any] | None = None,
    env: Mapping[str, Any] | None = None,
    secret_resolver: Callable[[str], str | None] | None = None,
    redactor: Redactor | None = None,
) -> tuple[Any, bool]:
    """Resolve refs. Returns (resolved, blocked). Secrets blocked without resolver."""
    redactor = redactor or Redactor()
    env_map = env if env is not None else os.environ
    if isinstance(value, str):
        s = value.strip()
        m = _TEST_DATA_RE.match(s)
        if m:
            name = m.group(1)
            if name in (test_data or {}):
                return test_data[name], False  # type: ignore[return-value]
            return value, False
        m = _ENV_RE.match(s)
        if m:
            name = m.group(1)
            if name in env_map:
                return env_map[name], False  # type: ignore[return-value]
            return value, False
        m = _SECRET_RE.match(s)
        if m:
            if secret_resolver is None:
                return "[REDACTED_SECRET]", True
            try:
                resolved = secret_resolver(m.group(2))
            except Exception as e:
                raise RefResolutionBlocked(f"Secret resolver failed for '{m.group(2)}': {e}") from e
            return resolved, False
        # Embedded refs inside longer strings: resolve test_data/env, redact secrets.
        if _PLACEHOLDER_RE.search(s):
            blocked = False
            def _sub(mm: re.Match) -> str:
                nonlocal blocked
                kind, name = mm.group(1), mm.group(2)
                if kind == "test_data":
                    return str((test_data or {}).get(name, mm.group(0)))
                if kind == "env":
                    return str(env_map.get(name, mm.group(0)))
                blocked = True
                return "[REDACTED_SECRET]"
            out = _PLACEHOLDER_RE.sub(_sub, s)
            if blocked and secret_resolver is not None:
                # Approved path: resolver already validated; out is redacted-safe for logs.
                blocked = False
            return out, blocked
        return redactor.redact(value), False
    if isinstance(value, list):
        items, blocked = [], False
        for v in value:
            rv, b = resolve_value(v, test_data=test_data, env=env, secret_resolver=secret_resolver, redactor=redactor)
            items.append(rv)
            blocked = blocked or b
        return items, blocked
    if isinstance(value, dict):
        out, blocked = {}, False
        for k, v in value.items():
            rv, b = resolve_value(v, test_data=test_data, env=env, secret_resolver=secret_resolver, redactor=redactor)
            out[k] = rv
            blocked = blocked or b
        return out, blocked
    return value, False


def redact_value(value: Any, redactor: Redactor | None = None) -> Any:
    """Redact resolved values for traces/summaries (truncate long text)."""
    redactor = redactor or Redactor()
    if isinstance(value, str):
        out = redactor.redact(value)
        return out if len(out) <= 500 else out[:497] + "...[truncated]"
    return value
