"""Multi-agent flow with handoffs (textbook Ch.4).

Rather than one monolithic super-agent, the procedure graph is split across
three specialized RoleAgents that hand off to one another:

  Planner   (N0–N6)  : opens, parses, clarifies, classifies intent
  Builder   (N7–N11)  : journeys, elements, locators, actions
  Validator (N12–N15) : assertions, reliability, code gen, review

Each RoleAgent has its OWN scratchpad (scoped short-term memory) so context
stays lean — the textbook's anti-bloat rule (each agent's memory << whole).
Handoffs pass a *shared thread* (the master AgentState) so downstream agents
inherit upstream conclusions without re-deriving them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..core.state import AgentState, NodeResult
from ..core.tracer import Tracer, trace
from ..reasoning.node_executor import NodeExecutor
from .graph import build_sdet_graph

logger = logging.getLogger("sdet_agent.multiagent")


@dataclass
class RoleAgent:
    name: str
    owns: set[str]
    executor: NodeExecutor
    # Per-agent scoped memory (Layer 4). The master state is the shared thread.
    memory: list[str] = field(default_factory=list)

    def handles(self, node_id: str) -> bool:
        return node_id in self.owns

    def execute(self, node, state: AgentState) -> NodeResult:
        result = self.executor.execute(node, state)
        if result.role == "agent":
            self.memory.append(f"{node.id}: {result.content[:200]}")
        return result


# Canonical segmentation of the 16-node graph into specialist roles.
SEGMENTS: dict[str, set[str]] = {
    "Planner": {"N0", "N1", "N2", "N3", "N4", "N5", "N6"},
    "Builder": {"N7", "N8", "N9", "N10", "N11"},
    "Validator": {"N12", "N13", "N14", "N15"},
}


def build_role_agents(executor: Optional[NodeExecutor] = None) -> dict[str, RoleAgent]:
    executor = executor or NodeExecutor()
    if getattr(executor, "use_qwen", False) or True:
        # Reuse any Qwen handlers already installed on the shared executor.
        pass
    return {
        name: RoleAgent(name=name, owns=owns, executor=executor)
        for name, owns in SEGMENTS.items()
    }


class MultiAgentOrchestrator:
    def __init__(self, tracer: Optional[Tracer] = None, max_turns: int = 35):
        self.graph = build_sdet_graph()
        self.tracer = tracer or Tracer()
        self.max_turns = max_turns
        self.shared_executor = NodeExecutor()
        self.agents = build_role_agents(self.shared_executor)

    def _agent_for(self, node_id: str) -> RoleAgent:
        for agent in self.agents.values():
            if agent.handles(node_id):
                return agent
        return self.agents["Planner"]

    def run(self, url: str, scenario: str, session_id: str = "") -> dict:
        state = AgentState(url=url, scenario=scenario, session_id=session_id, tracer=self.tracer)
        current = self.graph.start_node_id
        turns = 0
        last_agent = ""
        handoffs = 0
        error: Optional[str] = None

        try:
            while not self.graph.is_terminal(current) and turns < self.max_turns:
                turns += 1
                node = self.graph.get_node(current)
                if node is None:
                    error = f"Unknown node {current}"
                    break
                agent = self._agent_for(node.id)
                if last_agent and agent.name != last_agent:
                    handoffs += 1
                    with self.tracer.span(f"handoff:{last_agent}->{agent.name}", "step") as span:
                        # Shared-thread handoff: pass conclusions via scratchpad
                        state.scratchpad.record_event(
                            "handoff", f"{last_agent} -> {agent.name}"
                        )
                        span.output = f"handoff to {agent.name}"
                last_agent = agent.name

                with self.tracer.span(f"node:{node.id}", "step") as span:
                    result = agent.execute(node, state)
                    state.add_node_result(result)
                    state.current_node = node.id
                    span.output = result.content[:200]

                if node.id == "N14":
                    from ..guardrails import build_guardrails, retry_with_guardrails
                    from ..reasoning.qwen_reasoner import extract_code
                    from ..reasoning.rule_reasoner import generate_code_template

                    gr = build_guardrails()
                    final, _, used_fb = retry_with_guardrails(
                        state.get("generated_code", ""),
                        {"url": url, "scenario": scenario},
                        gr,
                        lambda fb, rs: generate_code_template(state),
                        lambda: generate_code_template(state),
                    )
                    state.set("generated_code", final)
                    state.set("guardrail_used_fallback", used_fb)

                successors = self.graph.successors(node.id)
                if not successors:
                    break
                if len(successors) == 1:
                    current = successors[0].target_id
                else:
                    chosen = result.metadata.get("branch")
                    nxt = None
                    if chosen:
                        for e in successors:
                            if e.condition_label == chosen:
                                nxt = e.target_id
                                break
                    if nxt is None:
                        for e in successors:
                            if e.condition_label:
                                nxt = e.target_id
                                break
                    current = nxt or successors[0].target_id

            success = current in ("T_SUCCESS",)
            if not success and current not in ("T_ABANDON", "T_ESCALATE"):
                error = error or "did not reach terminal"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Multi-agent run crashed")
            success = False
            error = str(exc)
            current = current or "N0"

        return {
            "success": success,
            "final_node": current,
            "handoffs": handoffs,
            "generated_code": state.get("generated_code", ""),
            "agent_memory": {name: a.memory for name, a in self.agents.items()},
            "trace_summary": self.tracer.summary(),
            "error": error,
        }


def draw_graph() -> str:
    """ASCII visualization of the multi-agent network (Ch.4: visualize the invisible)."""
    lines = ["SDET Multi-Agent Network", "=" * 40]
    for name, owns in SEGMENTS.items():
        ordered = sorted(owns, key=lambda x: int(x[1:]))
        lines.append(f"[{name}]  owns: {' → '.join(ordered)}")
    lines.append("-" * 40)
    lines.append("Handoffs: Planner → Builder → Validator")
    lines.append("Shared thread: AgentState (scratchpad + context)")
    return "\n".join(lines)
