"""Tracing: the agent's debugging microscope (textbook Ch.2).

Without tracing, debugging a multi-step agent is like fixing a car engine
blindfolded. The Tracer records every LLM call and tool invocation, their
inputs/outputs, and timing, so you can see exactly why the agent took a
wrong turn.

Traces are emitted as structured JSON lines plus a human-readable log.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterator

logger = logging.getLogger("sdet_agent.tracer")


@dataclass
class TraceSpan:
    span_id: str
    name: str
    kind: str  # "llm" | "tool" | "step" | "guardrail"
    started_at: float
    ended_at: float = 0.0
    input: Any = None
    output: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        if not self.ended_at:
            return 0.0
        return round((self.ended_at - self.started_at) * 1000, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "name": self.name,
            "kind": self.kind,
            "duration_ms": self.duration_ms,
            "input": self.input,
            "output": self.output,
            "metadata": self.metadata,
        }


class _SpanCM:
    """Context-manager wrapper around a TraceSpan that records on exit."""

    def __init__(self, tracer: "Tracer", span: TraceSpan):
        self._tracer = tracer
        self._span = span

    def __enter__(self) -> TraceSpan:
        return self._span

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self._span.metadata["error"] = str(exc)
        self._tracer.finish(self._span)


class Tracer:
    """Collects trace spans for a single agent run."""

    def __init__(self, enabled: bool = True, run_id: str | None = None):
        self.enabled = enabled
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.spans: list[TraceSpan] = []

    def span(self, name: str, kind: str, input: Any = None) -> _SpanCM:
        """Open a span as a context manager.

        Usage:
            with tracer.span("node:N2", "step", input={...}) as span:
                ... do work ...
                span.output = result
        """
        raw = TraceSpan(
            span_id=uuid.uuid4().hex[:8],
            name=name,
            kind=kind,
            started_at=time.time(),
            input=input,
        )
        if self.enabled:
            logger.debug("[trace:%s] %s (%s) start", self.run_id, name, kind)
        return _SpanCM(self, raw)

    def finish(self, span: TraceSpan, output: Any = None, **metadata: Any) -> None:
        span.ended_at = time.time()
        span.output = output
        span.metadata.update(metadata)
        self.spans.append(span)
        if self.enabled:
            logger.debug(
                "[trace:%s] %s (%s) done in %sms",
                self.run_id,
                span.name,
                span.kind,
                span.duration_ms,
            )

    def summary(self) -> dict[str, Any]:
        total_ms = sum(s.duration_ms for s in self.spans)
        by_kind: dict[str, int] = {}
        for s in self.spans:
            by_kind[s.kind] = by_kind.get(s.kind, 0) + 1
        return {
            "run_id": self.run_id,
            "total_spans": len(self.spans),
            "total_duration_ms": round(total_ms, 2),
            "spans_by_kind": by_kind,
        }

    def to_jsonl(self, path: str) -> None:
        with open(path, "w") as f:
            for s in self.spans:
                f.write(json.dumps(s.to_dict()) + "\n")


@contextlib.contextmanager
def trace(name: str, kind: str = "step", input: Any = None) -> Iterator[TraceSpan]:
    """Lightweight trace context manager for inline use.

    Usage:
        with trace("plan_actions", "step", input={"x": 1}) as span:
            ... do work ...
            span.output = result
    """
    span = TraceSpan(
        span_id=uuid.uuid4().hex[:8],
        name=name,
        kind=kind,
        started_at=time.time(),
        input=input,
    )
    try:
        yield span
    finally:
        span.ended_at = time.time()
        if span.output is not None or span.metadata:
            logger.debug("[trace] %s (%s) %sms", name, kind, span.duration_ms)
