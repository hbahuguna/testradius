"""D11-safe LLM context.

The LLM may see ONLY: changed file paths, selected symbol names, aggregate
counts/confidence, and the conversation. Never repo code content, test bodies,
diffs, or file contents.

Every context passed to an LLM in this package is built here through
``build_context`` and validated by ``assert_d11_safe`` so a future edit cannot
silently start shipping code to a provider.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from ..privacy import LLM_CONTEXT_ALLOWED, PrivacyError, assert_llm_context_safe

# The complete allowlist of keys permitted in an LLM context (single-sourced
# from tia_agent.privacy so the policy and its enforcement cannot drift).
ALLOWED_KEYS = LLM_CONTEXT_ALLOWED

# Keys that must never appear (content-bearing).
FORBIDDEN_KEYS = frozenset({
    "code", "content", "source", "diff", "patch", "body", "snippet",
    "tests",  # full test objects include file/name; excluded from LLM context
    "file_content", "raw", "text",
})


def changed_files(paths: Optional[Iterable[str]]) -> List[str]:
    return sorted({str(p) for p in (paths or [])})


def symbol_names(raw: Optional[Mapping[str, Any]], limit: int = 50) -> List[str]:
    """Pull only symbol *names* out of an analyze-pr response (never code)."""
    if not raw:
        return []
    names: List[str] = []
    seen = set()
    for item in raw.get("results", []) or []:
        name = item.get("symbol_name")
        if name and name not in seen:
            seen.add(name)
            names.append(str(name))
    return names[:limit]


def build_context(
    *,
    repo: Optional[str] = None,
    pr_number: Optional[int] = None,
    changed_file_paths: Optional[Iterable[str]] = None,
    raw: Optional[Mapping[str, Any]] = None,
    symbols: Optional[Sequence[str]] = None,
    tests_selected: Optional[int] = None,
    total_affected_tests: Optional[int] = None,
    total_tests_in_repo: Optional[int] = None,
    fallback_used: Optional[bool] = None,
    fallback_reason: Optional[str] = None,
    confidence: Optional[str] = None,
    instrumented: Optional[bool] = None,
    evidence_fresh: Optional[bool] = None,
) -> Dict[str, Any]:
    """Assemble a whitelisted, content-free context for the LLM."""
    ctx: Dict[str, Any] = {}
    if repo is not None:
        ctx["repo"] = repo
    if pr_number is not None:
        ctx["pr_number"] = pr_number
    if changed_file_paths is not None:
        ctx["changed_files"] = changed_files(changed_file_paths)
    elif raw is not None:
        # The backend returns paths under one of these keys.
        paths = raw.get("pr_files") or raw.get("file_paths") or []
        ctx["changed_files"] = changed_files(paths)
    if symbols is not None:
        ctx["symbols"] = list(symbols)
    elif raw is not None:
        ctx["symbols"] = symbol_names(raw)
    for key, val in (
        ("tests_selected", tests_selected),
        ("total_affected_tests", total_affected_tests),
        ("total_tests_in_repo", total_tests_in_repo),
        ("fallback_used", fallback_used),
        ("fallback_reason", fallback_reason),
        ("confidence", confidence),
        ("instrumented", instrumented),
        ("evidence_fresh", evidence_fresh),
    ):
        if val is not None:
            ctx[key] = val
    assert_d11_safe(ctx)
    return ctx


def assert_d11_safe(context: Mapping[str, Any]) -> None:
    """Raise if a context carries anything beyond the D11 allowlist."""
    for key in context:
        if key in FORBIDDEN_KEYS:
            raise PrivacyError(f"forbidden field '{key}' in LLM context (D11)")
    assert_llm_context_safe(context)
    # Guard against code sneaking in through an allowed list field.
    for key in ("changed_files", "symbols"):
        for item in context.get(key, []) or []:
            if not isinstance(item, str):
                raise PrivacyError(f"non-string entry in '{key}' (D11)")
            if "\n" in item:
                raise PrivacyError(f"multi-line value in '{key}' looks like code (D11)")