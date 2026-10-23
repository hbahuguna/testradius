"""Citation validation shared by the planner and executor (E2-S2)."""

from __future__ import annotations

from .context import ContextClient, ContextNode
from .types import Citation, Plan, PlanStep


class CitationError(Exception):
    pass


class CitationResolver:
    def __init__(self, context: ContextClient):
        self._context = context

    async def resolve(self, citation: Citation) -> ContextNode:
        node = await self._context.get(citation.node_id)
        if node is None:
            raise CitationError(f"unknown citation: {citation.node_id}")
        return node

    async def resolve_all(self, citations: list[Citation]) -> list[ContextNode]:
        if not citations:
            raise CitationError("step has no citations")
        return [await self.resolve(citation) for citation in citations]

    async def validate_step(self, step: PlanStep) -> None:
        await self.resolve_all(step.citations)

    async def validate_plan(self, plan: Plan) -> None:
        if not plan.steps:
            raise CitationError("plan has no steps")
        for step in plan.steps:
            await self.validate_step(step)
