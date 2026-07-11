"""Short-term memory: the agent's journal/scratchpad.

Per the textbook Ch.3, an agent does not inherently "remember" what it did
two steps ago across independent LLM calls. The scratchpad gives it a
continuous thread of thought: load_journal() at the start of a step,
record_event() after acting.

This prevents context-window overload and is the Layer-4 memory primitive.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class JournalEntry:
    step: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


class Scratchpad:
    """A simple, persistent-in-memory journal used as short-term memory."""

    def __init__(self, max_entries: int = 100):
        self._entries: list[JournalEntry] = []
        self._max_entries = max_entries

    def record_event(self, step: str, content: str, **metadata: Any) -> None:
        """Append a summary of what happened to the journal."""
        self._entries.append(JournalEntry(step=step, content=content, metadata=dict(metadata)))
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries :]

    def load_journal(self) -> str:
        """Return the full journal as a flat text block for prompt context."""
        if not self._entries:
            return "(journal empty — no prior steps recorded)"
        parts: list[str] = []
        for i, e in enumerate(self._entries, 1):
            parts.append(f"{i}. [{e.step}] {e.content}")
        return "\n".join(parts)

    def last(self, step: str | None = None) -> JournalEntry | None:
        """Return the most recent entry, optionally filtered by step name."""
        for e in reversed(self._entries):
            if step is None or e.step == step:
                return e
        return None

    def clear(self) -> None:
        self._entries.clear()

    def to_list(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._entries]
