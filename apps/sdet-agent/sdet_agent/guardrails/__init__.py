"""Guardrails package: assemble the standard guardrail set."""

from __future__ import annotations

from .base import Guardrail, GuardrailResult
from .code_validator import check_code_validity
from .locator_checker import check_locators, check_assertions
from .retry_loop import run_guardrails, retry_with_guardrails

STANDARD_GUARDRAILS = [
    Guardrail("code_validity", check_code_validity),
    Guardrail("locator_strategy", check_locators),
    Guardrail("assertion_coverage", check_assertions),
]


def build_guardrails() -> list[Guardrail]:
    return list(STANDARD_GUARDRAILS)


__all__ = [
    "Guardrail",
    "GuardrailResult",
    "build_guardrails",
    "run_guardrails",
    "retry_with_guardrails",
    "check_code_validity",
    "check_locators",
    "check_assertions",
]
