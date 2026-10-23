"""Typed agent primitives shared by the planner, executor, and runtime.

These are internal contracts; the wire contract remains ``RunEvent`` in
``cell.models``. Keeping the internal model small makes it possible to replay a
plan from events without importing a provider SDK.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Citation:
    node_id: str
    label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "label": self.label}


@dataclass(frozen=True)
class ToolCall:
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    citations: tuple[Citation, ...] = ()


@dataclass
class PlanStep:
    step_id: str
    intent: str
    tool: str | None
    arguments: dict[str, Any] = field(default_factory=dict)
    citations: list[Citation] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    expected_outcome: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "intent": self.intent,
            "tool": self.tool,
            "arguments": self.arguments,
            "citations": [citation.to_dict() for citation in self.citations],
            "depends_on": self.depends_on,
            "expected_outcome": self.expected_outcome,
        }


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total,
        }


@dataclass
class Plan:
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "steps": [step.to_dict() for step in self.steps],
            "citations": [citation.to_dict() for citation in self.citations],
            "usage": self.usage.to_dict(),
        }


@dataclass
class Completion:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


@dataclass
class ToolResult:
    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    evidence: list[str] = field(default_factory=list)


@dataclass
class StepResult:
    step_id: str
    intent: str
    ok: bool
    verdict: str
    detail: str
    citations: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    action: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    observation: str = ""
    usage: Usage = field(default_factory=Usage)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "step_id": self.step_id,
            "thought": self.intent,
            "action": self.action,
            "args": self.arguments,
            "observation": self.observation or self.detail,
            "citations": self.citations,
            "usage": self.usage.to_dict(),
            "duration_ms": self.duration_ms,
            "ok": self.ok,
            "verdict": self.verdict,
            "detail": self.detail,
            "evidence": self.evidence,
        }


@dataclass
class AgentResult:
    plan: Plan
    steps: list[StepResult] = field(default_factory=list)
    verdict: str = "passed"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "steps": [step.to_dict() for step in self.steps],
            "verdict": self.verdict,
            "reason": self.reason,
        }
