"""Node executor: dispatches each graph node to a handler.

Handlers produce a NodeResult. Routing hubs embed their chosen branch in
`metadata["branch"]` so the Agent can pick the correct successor edge.

Design: handlers are pure functions of (node, state). The executor also
records each step into the tracer. In Phase 2, generative handlers will call
the Qwen SLM — the dispatch shape stays identical.
"""

from __future__ import annotations

import logging
from typing import Callable

from ..core.state import AgentState, NodeResult
from ..core.tracer import Tracer
from .rule_reasoner import (
    classify_feature,
    classify_intent,
    needs_clarification,
    generate_code_template,
)
from .templates import NODE_SYSTEM_PROMPTS

logger = logging.getLogger("sdet_agent.executor")


class NodeExecutor:
    def __init__(self, tracer: Tracer | None = None):
        self.tracer = tracer or Tracer(enabled=False)
        self._handlers: dict[str, Callable[[AgentState], NodeResult]] = {
            "N0": self._open,
            "N1": self._user_request,
            "N2": self._parse,
            "N3": self._clarify_hub,
            "N4": self._clarify_details,
        }
        _register_defaults(self)

    def register(self, node_id: str, handler: Callable[[AgentState], NodeResult]) -> None:
        self._handlers[node_id] = handler

    def set_qwen_handlers(self, mapping: dict[str, Callable[[AgentState], NodeResult]]) -> None:
        """Phase 2 hook: replace generative nodes with Qwen-backed handlers."""
        self._handlers.update(mapping)

    def execute(self, node, state: AgentState) -> NodeResult:
        handler = self._handlers.get(node.id)
        if handler is None:
            return NodeResult(
                node_id=node.id,
                role=node.role.value,
                content=f"[{node.name}] (no handler — passing through)",
            )
        with self.tracer.span(f"exec:{node.id}", "step") as span:
            result = handler(state)
            span.output = result.content[:200]
        return result

    # --- handlers -----------------------------------------------------------

    def _open(self, state: AgentState) -> NodeResult:
        return NodeResult(
            node_id="N0",
            role="agent",
            content=(
                "Hello! I'm an expert SDET specializing in Playwright UI automation. "
                "I'll generate a production-quality test from your scenario using a "
                "structured 16-step procedure. Please describe what you'd like to test."
            ),
        )

    def _user_request(self, state: AgentState) -> NodeResult:
        return NodeResult(
            node_id="N1",
            role="user",
            content=state.scenario or "Generate a test for the page.",
        )

    def _parse(self, state: AgentState) -> NodeResult:
        feature = classify_feature(state.scenario)
        state.set("feature_type_candidate", feature.label)
        content = (
            f"Analyzed requirement. Feature type candidate: {feature.label}. "
            f"Reasoning: {feature.reasoning}"
        )
        return NodeResult(node_id="N2", role="agent", content=content)

    def _clarify_hub(self, state: AgentState) -> NodeResult:
        if needs_clarification(state.scenario):
            return NodeResult(
                node_id="N3",
                role="agent",
                content="I need more details to proceed — what page/feature and which actions?",
                metadata={"branch": "needs_clarification"},
            )
        return NodeResult(
            node_id="N3",
            role="agent",
            content="Requirement is clear enough to proceed.",
            metadata={"branch": "requirement_clear"},
        )

    def _clarify_details(self, state: AgentState) -> NodeResult:
        # In a real interactive run this comes from the user; here we accept
        # the existing scenario as sufficient and proceed.
        return NodeResult(
            node_id="N4",
            role="user",
            content=state.scenario or "(provided scenario)",
        )

    # --- remaining nodes (N5..N15) ------------------------------------------
    # Defined as methods so they can be registered in __init__ below.

    def _determine_intent(self, state: AgentState) -> NodeResult:
        intent = classify_intent(state.scenario)
        state.set("intent", intent.label)
        return NodeResult(
            node_id="N5",
            role="agent",
            content=f"Classified as **{intent.label}** test. {intent.reasoning}",
            metadata={"branch": intent.label},
        )

    def _intent_hub(self, state: AgentState) -> NodeResult:
        intent = state.get("intent", "positive")
        return NodeResult(
            node_id="N6",
            role="agent",
            content=f"Proceeding with a **{intent}** test.",
            metadata={"branch": intent},
        )

    def _identify_journey(self, state: AgentState) -> NodeResult:
        url = state.url or "target page"
        return NodeResult(
            node_id="N7",
            role="agent",
            content=f"User journey: start at {url}, perform the described actions, "
            f"verify the expected end state.",
        )

    def _feature_hub(self, state: AgentState) -> NodeResult:
        feature = state.get("feature_type_candidate") or state.get("feature_type") or "form"
        state.set("feature_type", feature)
        return NodeResult(
            node_id="N8",
            role="agent",
            content=f"This is a **{feature}** feature.",
            metadata={"branch": feature},
        )

    def _identify_elements(self, state: AgentState) -> NodeResult:
        # ToolRegistry.call() emits tool_call/tool_result events itself, so the
        # DOM parse surfaces in the stream without manual emits here.
        url = state.url or ""
        elements_desc = "Identified interactable elements from the scenario."
        if url:
            try:
                from ..tools import build_registry

                reg = build_registry()
                elements = reg.call("dom_analyze", {"url": url})
                if isinstance(elements, list) and elements and "error" not in elements[0]:
                    picks = [
                        e.get("suggested_locator")
                        for e in elements[:12]
                        if e.get("suggested_locator")
                    ]
                    elements_desc = (
                        f"Analyzed {url} and found {len(elements)} interactive elements. "
                        f"Locator hints: " + "; ".join(picks)
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("dom_analyze failed for %s: %s", url, exc)
        return NodeResult(node_id="N9", role="agent", content=elements_desc)

    def _determine_locators(self, state: AgentState) -> NodeResult:
        return NodeResult(
            node_id="N10",
            role="agent",
            content="Locator strategy: prefer accessible locators "
            "(getByRole > getByLabel > getByText > getByTestId > CSS).",
        )

    def _plan_actions(self, state: AgentState) -> NodeResult:
        return NodeResult(
            node_id="N11",
            role="agent",
            content="Action sequence planned: navigate, interact, assert, verify.",
        )

    def _design_assertions(self, state: AgentState) -> NodeResult:
        return NodeResult(
            node_id="N12",
            role="agent",
            content="Assertions designed for each checkpoint (visibility, value, URL).",
        )

    def _add_reliability(self, state: AgentState) -> NodeResult:
        return NodeResult(
            node_id="N13",
            role="agent",
            content="Reliability hardening applied: auto-waiting assertions, no fixed timeouts.",
        )

    def _generate_code(self, state: AgentState) -> NodeResult:
        code = generate_code_template(state)
        state.set("generated_code", code)
        return NodeResult(
            node_id="N14",
            role="agent",
            content=f"Generated Playwright test:\n\n```typescript\n{code}\n```",
        )

    def _review_hub(self, state: AgentState) -> NodeResult:
        return NodeResult(
            node_id="N15",
            role="agent",
            content="The test generation is complete. Do you accept this test, "
            "need revisions, or would you like to abandon?",
            metadata={"branch": "accept"},
        )


def _register_defaults(executor: NodeExecutor) -> None:
    for nid, fn in [
        ("N5", executor._determine_intent),
        ("N6", executor._intent_hub),
        ("N7", executor._identify_journey),
        ("N8", executor._feature_hub),
        ("N9", executor._identify_elements),
        ("N10", executor._determine_locators),
        ("N11", executor._plan_actions),
        ("N12", executor._design_assertions),
        ("N13", executor._add_reliability),
        ("N14", executor._generate_code),
        ("N15", executor._review_hub),
    ]:
        executor.register(nid, fn)
