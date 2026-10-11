"""Run-command building (E5/O1).

Turns validated test objects into the exact commands a user should run. Python
maps to ``pytest``; TypeScript/Playwright maps to ``npx playwright test`` (or
``npx vitest run`` / ``npx jest`` when the checkout declares those runners).
Commands are deduped and deterministic.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_PLAYWRIGHT_SUFFIXES = (".spec.ts", ".spec.tsx", ".spec.js", ".spec.jsx", ".spec.mjs")
_JS_LANGUAGES = ("typescript", "javascript", "playwright")


def build_run_commands(
    tests: List[Dict[str, Any]],
    runner: Optional[str] = None,
) -> List[str]:
    """One command per distinct target, in first-seen order."""
    commands: List[str] = []
    seen: set = set()
    for t in tests:
        cmd = _command_for(t, runner)
        if not cmd or cmd in seen:
            continue
        seen.add(cmd)
        commands.append(cmd)
    return commands


def _command_for(test: Dict[str, Any], runner: Optional[str]) -> Optional[str]:
    language = test.get("language", "unknown")
    file = test.get("file", "")
    nodeid = test.get("nodeid") or file
    if not file:
        return None
    if language == "python":
        return f"pytest {nodeid}"
    if language in _JS_LANGUAGES:
        resolved = runner or ("playwright" if file.endswith(_PLAYWRIGHT_SUFFIXES) else "vitest")
        if resolved == "playwright":
            return f"npx playwright test {file}"
        if resolved == "jest":
            return f"npx jest {file}"
        return f"npx vitest run {file}"
    return None
