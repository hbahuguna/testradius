"""Guardrails for agentic (goal-driven) execution.

Agentic tests trade determinism for adaptability, so explicit guardrails keep
the agent inside safe bounds -- exactly the constraints Slack's writeup calls
for (limits on allowed actions, exploration boundaries, and stop conditions).
These are evaluated every turn by the AgenticExecutor.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

# Actions an agent is allowed to take against a live browser during a run.
ALLOWED_AGENT_ACTIONS = {
    "navigate", "click", "type", "select", "wait",
    "assert_visible", "assert_text", "assert_url", "done", "fail",
}


@dataclass
class GuardrailVerdict:
    allow: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"allow": self.allow, "reason": self.reason}


def check_action_allowed(action: str, constraints: dict[str, Any]) -> GuardrailVerdict:
    """Reject actions outside the allowed set defined in the goal spec."""
    allowed = constraints.get("allowed_actions")
    if not allowed:
        return GuardrailVerdict(True, "no allowed_actions constraint")
    if action in ("done", "fail"):
        return GuardrailVerdict(True, "terminal action")
    if action in set(allowed):
        return GuardrailVerdict(True, "action in allowed set")
    return GuardrailVerdict(False, f"action '{action}' not in allowed_actions")


def should_stop(
    start_ts: float,
    steps: int,
    max_turns: int,
    stopping: dict[str, Any],
    cost_estimate_usd: float = 0.0,
) -> GuardrailVerdict:
    """Evaluate stopping conditions (turns, duration, cost)."""
    if steps >= max_turns:
        return GuardrailVerdict(False, f"max_turns ({max_turns}) reached")
    max_dur = stopping.get("max_duration_seconds")
    if max_dur:
        elapsed = time.time() - start_ts
        if elapsed >= float(max_dur):
            return GuardrailVerdict(False, f"max_duration_seconds ({max_dur}) exceeded")
    max_cost = stopping.get("max_cost_usd")
    if max_cost and cost_estimate_usd >= float(max_cost):
        return GuardrailVerdict(False, f"max_cost_usd ({max_cost}) exceeded")
    return GuardrailVerdict(True, "within limits")
