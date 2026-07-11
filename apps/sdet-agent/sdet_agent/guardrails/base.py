"""Guardrail base types (textbook Ch.4: back checks with hard-coded logic).

A Guardrail is a deterministic validator over generated test code + context.
It never relies on the LLM's stochastic self-assessment for pass/fail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class GuardrailResult:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


class Guardrail:
    def __init__(self, name: str, check: Callable[[str, dict], tuple[bool, str]]):
        self.name = name
        self._check = check

    def run(self, code: str, context: dict) -> GuardrailResult:
        passed, detail = self._check(code, context)
        return GuardrailResult(name=self.name, passed=passed, detail=detail)
