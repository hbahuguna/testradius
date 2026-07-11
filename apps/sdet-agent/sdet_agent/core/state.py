"""Agent state: the live working memory shared across the Sense-Plan-Act-Learn loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .scratchpad import Scratchpad
from .tracer import Tracer


@dataclass
class NodeResult:
    """Structured output produced by executing a single graph node."""

    node_id: str
    role: str  # "agent" | "user" | "terminal"
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata,
        }


@dataclass
class AgentState:
    """Mutable state object threaded through the agent loop.

    Holds the URL under test, the user scenario, the 16-node procedure
    context, and the scratchpad/journal used for short-term memory.
    """

    url: str = ""
    scenario: str = ""
    session_id: str = ""

    current_node: str = "N0"
    context: dict[str, Any] = field(default_factory=dict)
    node_history: list[NodeResult] = field(default_factory=list)

    scratchpad: Scratchpad = field(default_factory=Scratchpad)
    tracer: Tracer = field(default_factory=Tracer)

    metadata: dict[str, Any] = field(default_factory=dict)

    def add_node_result(self, result: NodeResult) -> None:
        self.node_history.append(result)

    def get_node_content(self, node_id: str) -> str:
        for r in self.node_history:
            if r.node_id == node_id:
                return r.content
        return ""

    def conversation_history(self) -> str:
        """Flat text representation of the journey so far (for prompt context)."""
        lines: list[str] = []
        for r in self.node_history:
            role = r.role.upper()
            lines.append(f"\n{role}: {r.content}")
        return "\n".join(lines)

    def set(self, key: str, value: Any) -> None:
        self.context[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.context.get(key, default)
