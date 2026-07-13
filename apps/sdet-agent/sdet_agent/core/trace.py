"""Execution traces for agentic (goal-driven) browser runs.

Structured, replayable records of an agentic test execution: every action the
agent took, why it took it, the page state it observed, and the assertions it
verified. Mirrors the observability requirement from the Slack agentic-testing
writeup -- execution logs are structured so teams can replay and inspect
failures.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class ActionTrace:
    """A single agent action during an agentic run."""

    step: int
    action: str  # navigate|click|type|select|wait|assert_*|done|fail
    target: str = ""
    kind: str = "auto"  # auto|role|label|text|placeholder|css
    value: str = ""
    ok: bool = True
    thought: str = ""
    url: str = ""
    interactive_elements: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: float = 0.0
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AssertionResult:
    """Outcome of one assertion checked at the end (or inline) of a run."""

    type: str  # visibility|text|url
    description: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionTrace:
    """Full replayable record of an agentic execution."""

    goal: str
    url: str
    backend: str
    steps: list[ActionTrace] = field(default_factory=list)
    assertions: list[AssertionResult] = field(default_factory=list)
    success: bool = False
    goal_reached: bool = False
    error: Optional[str] = None
    final_url: str = ""
    total_duration_ms: float = 0.0
    token_estimate: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "url": self.url,
            "backend": self.backend,
            "success": self.success,
            "goal_reached": self.goal_reached,
            "error": self.error,
            "final_url": self.final_url,
            "total_duration_ms": self.total_duration_ms,
            "token_estimate": self.token_estimate,
            "steps": [s.to_dict() for s in self.steps],
            "assertions": [a.to_dict() for a in self.assertions],
        }

    def to_jsonl(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            for step in self.steps:
                fh.write(json.dumps({"kind": "step", **step.to_dict()}, default=str) + "\n")
            for a in self.assertions:
                fh.write(json.dumps({"kind": "assertion", **a.to_dict()}, default=str) + "\n")
            fh.write(
                json.dumps(
                    {"kind": "summary", "success": self.success, "goal_reached": self.goal_reached,
                     "final_url": self.final_url, "error": self.error},
                    default=str,
                )
                + "\n"
            )
