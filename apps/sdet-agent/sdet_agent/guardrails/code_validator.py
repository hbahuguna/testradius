"""Code validity guardrail: syntactically sane Playwright TypeScript.

Uses tree-sitter when available; otherwise falls back to a heuristic scan
so the guardrail is always runnable. Deterministic either way.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("sdet_agent.guardrails.code")

_REQUIRED_TOKENS = [("import", "import {"), ("test", "test("), ("expect", "expect(")]


def _heuristic_check(code: str) -> tuple[bool, str]:
    problems: list[str] = []
    for label, token in _REQUIRED_TOKENS:
        if token not in code:
            problems.append(f"missing {label} ({token})")
    # Balanced braces / parens
    for open_ch, close_ch in [("{", "}"), ("(", ")"), ("[", "]")]:
        if code.count(open_ch) != code.count(close_ch):
            problems.append(f"unbalanced {open_ch}{close_ch}")
    if problems:
        return False, "; ".join(problems)
    return True, "heuristic structural check passed"


def _treesitter_check(code: str) -> tuple[bool, str]:
    try:
        from tree_sitter import Language, Parser
        from tree_sitter_typescript import language as ts_lang
    except ImportError:
        return _heuristic_check(code)
    try:
        parser = Parser()
        parser.set_language(Language(ts_lang()))
        tree = parser.parse(code.encode("utf-8"))
        if tree.root_node.has_error:
            return False, "tree-sitter reported a syntax error"
        return True, "tree-sitter parse OK"
    except Exception as exc:  # noqa: BLE001
        logger.debug("tree-sitter unavailable: %s", exc)
        return _heuristic_check(code)


def check_code_validity(code: str, context: dict) -> tuple[bool, str]:
    if not code.strip():
        return False, "empty generated code"
    return _treesitter_check(code)
