"""Executor (E2-S11): run a validated plan one cited step at a time."""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .citations import CitationResolver
from .mcp import MCPDenied, MCPError, ToolRegistry
from .types import AgentResult, Plan, StepResult, ToolResult, Usage

Emit = Callable[[str, dict[str, Any]], None | Awaitable[None]]


class AgentCancelled(Exception):
    pass


class Executor:
    def __init__(
        self,
        resolver: CitationResolver,
        registry: ToolRegistry,
        *,
        block_on_a11y_violation: bool = True,
        max_repetitions: int = 2,
    ):
        self._resolver = resolver
        self._registry = registry
        self._block_on_a11y = block_on_a11y_violation
        self._max_repetitions = max_repetitions

    async def execute(
        self,
        plan: Plan,
        *,
        is_cancelled: Callable[[], bool] = lambda: False,
        emit: Emit | None = None,
    ) -> AgentResult:
        result = AgentResult(plan=plan)
        await self._resolver.validate_plan(plan)
        seen: dict[str, int] = {}
        for step in plan.steps:
            if is_cancelled():
                raise AgentCancelled("run cancelled")
            started = time.monotonic()
            citation_ids = [citation.node_id for citation in step.citations]
            await _emit(
                emit,
                "step",
                {
                    "event": "step.started",
                    "schema_version": "1",
                    "step_id": step.step_id,
                    "thought": step.intent,
                    "action": step.tool,
                    "args": _safe_arguments(step.arguments),
                    "citations": citation_ids,
                    "usage": Usage().to_dict(),
                },
            )
            if step.tool is None:
                step_result = StepResult(
                    step_id=step.step_id,
                    intent=step.intent,
                    ok=True,
                    verdict="passed",
                    detail="planning step",
                    citations=citation_ids,
                    observation="planning step",
                    duration_ms=_elapsed_ms(started),
                )
                result.steps.append(step_result)
                await _emit(emit, "step", {"event": "step.completed", **step_result.to_dict()})
                continue

            key = f"{step.tool}:{json.dumps(step.arguments, sort_keys=True, default=str)}"
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > self._max_repetitions:
                step_result = _failed(step, citation_ids, "LoopDetected", started)
                result.steps.append(step_result)
                await _emit(
                    emit,
                    "verdict",
                    {
                        "event": "loop.detected",
                        "step_id": step.step_id,
                        "verdict": "failed",
                        "reason": "LoopDetected",
                    },
                )
                await self._finish(result, step_result, emit)
                return result

            await _emit(
                emit,
                "tool",
                {
                    "event": "tool.called",
                    "step_id": step.step_id,
                    "tool": step.tool,
                    "arguments": _safe_arguments(step.arguments),
                    "citations": citation_ids,
                },
            )
            try:
                tool_result = await self._registry.call(
                    "executor", step.tool, step.arguments, citation_ids
                )
            except MCPDenied as exc:
                step_result = _failed(step, citation_ids, f"denied:{exc.kind}", started)
                result.steps.append(step_result)
                await _emit(
                    emit,
                    "tool",
                    {
                        "event": "tool.denied",
                        "step_id": step.step_id,
                        "tool": step.tool,
                        "reason": exc.kind,
                    },
                )
                await self._finish(result, step_result, emit)
                return result
            except MCPError as exc:
                step_result = _failed(step, citation_ids, exc.kind, started)
                result.steps.append(step_result)
                await _emit(
                    emit,
                    "tool",
                    {
                        "event": "tool.failed",
                        "step_id": step.step_id,
                        "tool": step.tool,
                        "reason": exc.kind,
                    },
                )
                await self._finish(result, step_result, emit)
                return result

            await _emit(
                emit,
                "tool",
                {
                    "event": "tool.completed",
                    "step_id": step.step_id,
                    "tool": step.tool,
                    "ok": tool_result.ok,
                    "citations": citation_ids,
                },
            )
            a11y = tool_result.output.get("violations") or []
            if a11y and self._block_on_a11y:
                step_result = StepResult(
                    step_id=step.step_id,
                    intent=step.intent,
                    ok=False,
                    verdict="testability_defect",
                    detail=f"blocking accessibility violations: {len(a11y)}",
                    citations=citation_ids,
                    evidence=tool_result.evidence,
                    action=step.tool,
                    arguments=_safe_arguments(step.arguments),
                    observation=f"{len(a11y)} accessibility violation(s)",
                    duration_ms=_elapsed_ms(started),
                )
                result.steps.append(step_result)
                await _emit(
                    emit,
                    "verdict",
                    {
                        "event": "a11y.blocked",
                        "step_id": step.step_id,
                        "verdict": "testability_defect",
                        "violations": a11y,
                        "citations": citation_ids,
                    },
                )
                await self._finish(result, step_result, emit)
                return result

            if not tool_result.ok:
                step_result = _failed(
                    step, citation_ids, tool_result.error or "tool_failed", started
                )
                step_result.evidence = tool_result.evidence
                result.steps.append(step_result)
                await self._finish(result, step_result, emit)
                return result

            step_result = StepResult(
                step_id=step.step_id,
                intent=step.intent,
                ok=True,
                verdict="passed",
                detail=_detail(tool_result),
                citations=citation_ids,
                evidence=tool_result.evidence,
                action=step.tool,
                arguments=_safe_arguments(step.arguments),
                observation=_detail(tool_result),
                duration_ms=_elapsed_ms(started),
            )
            result.steps.append(step_result)
            await _emit(emit, "step", {"event": "step.completed", **step_result.to_dict()})

        result.verdict = "passed"
        return result

    async def _finish(
        self, result: AgentResult, step_result: StepResult, emit: Emit | None
    ) -> None:
        result.verdict = step_result.verdict
        result.reason = step_result.detail
        await _emit(emit, "step", {"event": "step.failed", **step_result.to_dict()})


def _failed(
    step: Any,
    citations: list[str],
    detail: str,
    started: float,
) -> StepResult:
    return StepResult(
        step_id=step.step_id,
        intent=step.intent,
        ok=False,
        verdict="failed",
        detail=detail,
        citations=citations,
        action=step.tool,
        arguments=_safe_arguments(step.arguments),
        observation=detail,
        duration_ms=_elapsed_ms(started),
    )


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _detail(result: ToolResult) -> str:
    if result.error:
        return result.error
    return "ok"


def _safe_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in arguments.items():
        lowered = key.lower()
        if any(term in lowered for term in ("secret", "password", "token", "api_key")):
            redacted[key] = "[redacted]"
        elif isinstance(value, str) and len(value) > 240:
            redacted[key] = value[:240] + "..."
        else:
            redacted[key] = value
    return redacted


async def _emit(emit: Emit | None, event_type: str, payload: dict[str, Any]) -> None:
    if emit is None:
        return
    outcome = emit(event_type, payload)
    if hasattr(outcome, "__await__"):
        await outcome
