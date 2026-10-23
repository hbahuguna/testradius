"""Planner (E2-S8): turn a goal + retrieved context into a validated plan.

The model returns JSON; the planner, not the model, decides whether a plan is
executable. Every step must cite a real context node and use an allowlisted tool.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .citations import CitationError, CitationResolver
from .context import ContextClient
from .mcp import MCPTool
from .provider import Provider, ProviderError
from .types import Citation, Plan, PlanStep, Usage

_SYSTEM = (
    "You are the TestRadius planner. Return only a JSON object with a steps array. "
    "Each step has intent, tool, arguments, citations, and optional depends_on. "
    "Every step must cite at least one supplied context node id. Do not invent ids. "
    "Do not use a tool that is not in the supplied tool list."
)


class PlanError(Exception):
    pass


class InsufficientContext(PlanError):
    pass


class Planner:
    def __init__(
        self,
        provider: Provider,
        context: ContextClient,
        resolver: CitationResolver,
        *,
        max_steps: int = 12,
    ):
        self._provider = provider
        self._context = context
        self._resolver = resolver
        self._max_steps = max_steps
        self.total_usage = Usage()

    async def plan(
        self,
        goal: str,
        *,
        tools: list[MCPTool],
        context_limit: int = 12,
    ) -> Plan:
        nodes = await self._context.retrieve(goal, limit=context_limit)
        if not nodes:
            raise InsufficientContext("no context nodes matched the goal")
        node_text = "\n".join(
            f"- {node.node_id} ({node.kind}): {node.label}" for node in nodes
        )
        tool_text = "\n".join(f"- {tool.name}: {tool.description}" for tool in tools)
        messages = [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Goal: {goal}\n\nContext nodes:\n{node_text}\n\n"
                    f"Allowed tools:\n{tool_text}\n\nReturn JSON only."
                ),
            },
        ]
        provider_tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in tools
        ]
        for attempt in range(2):
            try:
                completion = await self._provider.complete(
                    messages, tools=provider_tools, max_tokens=2048
                )
            except ProviderError as exc:
                raise PlanError(f"provider_{exc.kind}") from exc
            self.total_usage = Usage(
                input_tokens=self.total_usage.input_tokens + completion.usage.input_tokens,
                output_tokens=self.total_usage.output_tokens + completion.usage.output_tokens,
            )
            try:
                return await self._parse_plan(
                    goal, completion.text, tools, usage=completion.usage
                )
            except PlanError as exc:
                if attempt == 1:
                    raise
                messages = [
                    *messages,
                    {"role": "assistant", "content": completion.text},
                    {
                        "role": "user",
                        "content": (
                            f"The plan was rejected: {exc}. "
                            "Return corrected JSON only, using only supplied context ids "
                            "and allowed tools."
                        ),
                    },
                ]
        raise PlanError("planner failed")  # pragma: no cover

    async def _parse_plan(
        self,
        goal: str,
        text: str,
        tools: list[MCPTool],
        *,
        usage: Usage,
    ) -> Plan:
        raw = _json_payload(text)
        if not isinstance(raw, dict) or not isinstance(raw.get("steps"), list):
            raise PlanError("planner returned invalid plan")
        raw_steps = raw["steps"]
        if not raw_steps:
            raise InsufficientContext("planner returned no steps")
        if len(raw_steps) > self._max_steps:
            raise PlanError("plan exceeds max_steps")

        allowed = {tool.name for tool in tools}
        steps: list[PlanStep] = []
        seen_ids: set[str] = set()
        for index, item in enumerate(raw_steps, start=1):
            if not isinstance(item, dict):
                raise PlanError("plan step is not an object")
            step_id = str(item.get("step_id") or f"step-{index}")
            if step_id in seen_ids:
                raise PlanError(f"duplicate step id: {step_id}")
            seen_ids.add(step_id)
            intent = str(item.get("intent") or "").strip()
            if not intent:
                raise PlanError("plan step has no intent")
            tool = item.get("tool")
            if tool is not None:
                tool = str(tool)
                if tool not in allowed:
                    raise PlanError(f"tool not available: {tool}")
            arguments = item.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise PlanError("plan step arguments must be an object")
            raw_citations = item.get("citations") or []
            if not isinstance(raw_citations, list) or not raw_citations:
                raise PlanError(f"step {step_id} has no citations")
            citations = [
                Citation(node_id=str(citation))
                if not isinstance(citation, dict)
                else Citation(
                    node_id=str(citation.get("node_id", "")),
                    label=citation.get("label"),
                )
                for citation in raw_citations
            ]
            depends_on = item.get("depends_on") or []
            if not isinstance(depends_on, list):
                raise PlanError("depends_on must be a list")
            step = PlanStep(
                step_id=step_id,
                intent=intent,
                tool=tool,
                arguments=arguments,
                citations=citations,
                depends_on=[str(dependency) for dependency in depends_on],
                expected_outcome=str(item.get("expected_outcome") or "").strip(),
            )
            try:
                await self._resolver.validate_step(step)
            except CitationError as exc:
                raise PlanError(str(exc)) from exc
            steps.append(step)

        _validate_dependencies(steps)
        return Plan(
            goal=goal,
            steps=steps,
            citations=[citation for step in steps for citation in step.citations],
            usage=usage,
        )


def _json_payload(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise PlanError("planner returned non-JSON output") from exc


def _validate_dependencies(steps: list[PlanStep]) -> None:
    ids = {step.step_id for step in steps}
    graph = {step.step_id: set(step.depends_on) for step in steps}
    for step_id, dependencies in graph.items():
        missing = dependencies - ids
        if missing:
            raise PlanError(f"step {step_id} depends on unknown step(s): {sorted(missing)}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visiting:
            raise PlanError("plan has a dependency cycle")
        if step_id in visited:
            return
        visiting.add(step_id)
        for dependency in graph[step_id]:
            visit(dependency)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in graph:
        visit(step_id)
