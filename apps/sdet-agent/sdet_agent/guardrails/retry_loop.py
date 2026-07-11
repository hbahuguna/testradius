"""Retry loop: deterministic guardrail enforcement with fallback.

When guardrails fail on generated code, re-invoke the generator with the
failure feedback (up to max_retries). If still failing, call the hard-coded
fallback so the agent always returns *something* valid (textbook Ch.4).
"""

from __future__ import annotations

import logging
from typing import Callable

from .base import Guardrail, GuardrailResult

logger = logging.getLogger("sdet_agent.guardrails.retry")


def run_guardrails(
    code: str,
    context: dict,
    guardrails: list[Guardrail],
) -> tuple[bool, list[GuardrailResult]]:
    results = [g.run(code, context) for g in guardrails]
    passed = all(r.passed for r in results)
    return passed, results


def retry_with_guardrails(
    initial_code: str,
    context: dict,
    guardrails: list[Guardrail],
    regenerate: Callable[[str, list[GuardrailResult]], str],
    fallback: Callable[[], str],
    max_retries: int = 2,
) -> tuple[str, list[GuardrailResult], bool]:
    """Run guardrails; on failure, ask `regenerate(feedback)`; else `fallback`.

    Returns (final_code, results, used_fallback).
    """
    code = initial_code
    passed, results = run_guardrails(code, context, guardrails)
    if passed:
        return code, results, False

    for attempt in range(1, max_retries + 1):
        feedback = "; ".join(f"[{r.name}] {r.detail}" for r in results if not r.passed)
        logger.info("Guardrail retry %d/%d: %s", attempt, max_retries, feedback)
        code = regenerate(feedback, results)
        passed, results = run_guardrails(code, context, guardrails)
        if passed:
            return code, results, False

    logger.warning("Guardrails still failing after %d retries; using fallback", max_retries)
    code = fallback()
    _, results = run_guardrails(code, context, guardrails)
    return code, results, True
