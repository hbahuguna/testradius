"""The Agent orchestrator: Sense-Plan-Act-Learn loop over the 16-node graph.

This is the heart of the system (textbook Ch.1 agent loop + Ch.4 flows).
The agent:

  Sense   -> read URL + scenario + load scratchpad journal
  Plan    -> traverse the procedure graph, routing through decision hubs
  Act     -> execute each node via reasoning (Qwen) or rules, calling tools
  Learn   -> record results into scratchpad, run guardrails, adjust

The graph is imported from the existing workbench procedure package so we
reuse the canonical 16-node state machine rather than re-implementing it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..core.state import AgentState, NodeResult
from ..core.tracer import Tracer
from ..reasoning.node_executor import NodeExecutor
from .graph import build_sdet_graph
from .graph import NodeRole

logger = logging.getLogger("sdet_agent.agent")


@dataclass
class AgentResult:
    """Final outcome of a full agent run."""

    success: bool
    session_id: str
    trace_summary: dict[str, Any]
    generated_code: str = ""
    node_history: list[dict[str, Any]] = field(default_factory=list)
    journal: list[dict[str, Any]] = field(default_factory=list)
    final_node: str = ""
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "session_id": self.session_id,
            "trace_summary": self.trace_summary,
            "generated_code": self.generated_code,
            "node_history": self.node_history,
            "journal": self.journal,
            "final_node": self.final_node,
            "error": self.error,
        }


class Agent:
    """Runs the SDET procedure graph as an agentic loop.

    Node handlers are registered in the NodeExecutor. Routing decisions at
    the four decision hubs (N3, N6, N8, N15) are made by rule-based or
    Qwen-driven classifiers (see reasoning/).
    """

    def __init__(
        self,
        executor: Optional[NodeExecutor] = None,
        tracer: Optional[Tracer] = None,
        max_turns: int = 35,
        use_qwen: bool = True,
        guardrails: Optional[list] = None,
    ):
        self.graph = build_sdet_graph()
        self.executor = executor or NodeExecutor()
        self.tracer = tracer or Tracer()
        self.max_turns = max_turns
        self.use_qwen = use_qwen
        if guardrails is None:
            from ..guardrails import build_guardrails

            guardrails = build_guardrails()
        self.guardrails = guardrails
        if use_qwen:
            try:
                from ..reasoning.llm_reasoner import LLMReasoner, build_llm_handlers

                reasoner = LLMReasoner()
                self.executor.set_qwen_handlers(build_llm_handlers(reasoner))
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM Reasoner wiring failed, using rule-based: %s", exc)

    def run(self, url: str, scenario: str, session_id: str = "") -> AgentResult:
        state = AgentState(url=url, scenario=scenario, session_id=session_id, tracer=self.tracer)
        self.tracer.run_id = state.session_id or self.tracer.run_id

        # Sense
        state.scratchpad.record_event(
            "sense", f"Initialized agent for url={url} scenario='{scenario}'"
        )

        current_id = self.graph.start_node_id
        turns = 0
        error: Optional[str] = None

        try:
            while not self.graph.is_terminal(current_id) and turns < self.max_turns:
                turns += 1
                node = self.graph.get_node(current_id)
                if node is None:
                    error = f"Unknown node: {current_id}"
                    break

                with self.tracer.span(f"node:{node.id}", "step", input={"scenario": scenario}) as span:
                    result = self.executor.execute(node, state)
                    state.add_node_result(result)
                    state.current_node = node.id
                    span.output = result.content[:200]
                    # record every agent step into the scratchpad
                    if result.role == "agent":
                        state.scratchpad.record_event(node.id, result.content[:400])

                # Guardrail enforcement right after code generation (N14)
                if node.id == "N14" and self.guardrails:
                    self._enforce_guardrails(state)

                # Route to next node
                current_id = self._route(node, result, state)
                if current_id is None:
                    error = f"No valid successor for node {node.id}"
                    break

            if current_id in ("T_SUCCESS",):
                success = True
            elif current_id in ("T_ABANDON", "T_ESCALATE"):
                success = False
                error = error or f"Terminated at {current_id}"
            else:
                success = False
                error = error or "Exceeded max turns without reaching terminal"

        except Exception as exc:  # noqa: BLE001 — surface as agent failure
            logger.exception("Agent loop crashed")
            success = False
            error = str(exc)
            current_id = current_id or "N0"

        generated = state.get("generated_code", "")
        return AgentResult(
            success=success,
            session_id=state.session_id,
            trace_summary=self.tracer.summary(),
            generated_code=generated,
            node_history=[r.to_dict() for r in state.node_history],
            journal=state.scratchpad.to_list(),
            final_node=current_id,
            error=error,
        )

    def _route(self, node, result: NodeResult, state: AgentState) -> Optional[str]:
        """Determine the next node id given the current node + its result.

        Uses graph edges. For decision hubs, the result metadata carries the
        chosen branch condition_label; otherwise we take the first (or only)
        successor edge whose condition matches.
        """
        successors = self.graph.successors(node.id)
        if not successors:
            return None

        # Terminal or single-path node
        if len(successors) == 1:
            return successors[0].target_id

        # Decision hub: pick the edge whose condition matches the chosen branch
        chosen = result.metadata.get("branch")
        if chosen:
            for edge in successors:
                if edge.condition_label == chosen:
                    return edge.target_id

        # Fallback: prefer a "default" non-empty condition, else first
        for edge in successors:
            if edge.condition_label:
                return edge.target_id
        return successors[0].target_id

    def _enforce_guardrails(self, state: AgentState) -> None:
        """Validate generated code; on failure, retry via Qwen then fallback.

        Updates state.generated_code and appends a guardrail journal entry.
        This is the Layer-5 Evaluation step (textbook Ch.4).
        """
        from ..guardrails import retry_with_guardrails
        from ..reasoning.llm_reasoner import extract_code # Updated import
        from ..reasoning.rule_reasoner import generate_code_template

        initial_code = state.get("generated_code", "")
        context = {
            "url": state.url,
            "scenario": state.scenario,
            "feature_type": state.get("feature_type", "form"),
            "intent": state.get("intent", "positive"),
        }

        def regenerate(feedback: str, results) -> str:
            # Re-ask Qwen (if available) with the failure feedback, else reuse.
            if self.use_qwen:
                try:
                    from ..reasoning.llm_reasoner import LLMReasoner, extract_code

                    reasoner = LLMReasoner()
                    prompt = (
                        f"Fix the Playwright test. Guardrail failures:\n{feedback}\n\n"
                        f"Scenario: {state.scenario}\nURL: {state.url}\n"
                        "Output ONLY valid TypeScript in a ```typescript block."
                    )
                    _, raw = reasoner.llm_factory.infer(prompt, max_tokens=1024)
                    code = extract_code(raw)
                    if code:
                        return code
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Guardrail regenerate failed: %s", exc)
            return generate_code_template(state)

        def fallback() -> str:
            return generate_code_template(state)

        final_code, results, used_fallback = retry_with_guardrails(
            initial_code=initial_code,
            context=context,
            guardrails=self.guardrails,
            regenerate=regenerate,
            fallback=fallback,
        )
        state.set("generated_code", final_code)
        state.set("guardrail_results", [r.to_dict() for r in results])
        state.set("guardrail_used_fallback", used_fallback)
        verdict = "PASSED" if all(r.passed for r in results) else "FAILED (fallback)"
        state.scratchpad.record_event(
            "guardrails", f"Code guardrails {verdict}; fallback={used_fallback}"
        )
