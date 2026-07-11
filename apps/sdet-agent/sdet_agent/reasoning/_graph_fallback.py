"""Standalone fallback for the 16-node SDET procedure graph.

Mirrors testsquad_workbench.sdet_procedure.graph so this package runs without
the workbench service installed. Prefer importing the canonical version via
core/graph.py; this is the fallback when that package is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple


class NodeRole(Enum):
    AGENT = "agent"
    USER = "user"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class Node:
    id: str
    name: str
    role: NodeRole
    prompt_template_id: str
    is_decision_hub: bool = False
    description: str = ""


@dataclass(frozen=True)
class Edge:
    source_id: str
    target_id: str
    condition_label: str = ""
    description: str = ""


@dataclass
class Path:
    node_ids: List[str]
    hub_decisions: Dict[str, str]
    edges_taken: List[Edge]
    metadata: Dict = field(default_factory=dict)

    @property
    def turn_node_ids(self) -> List[str]:
        return [
            nid
            for nid in self.node_ids
            if nid not in ("T_SUCCESS", "T_ABANDON", "T_ESCALATE")
        ]

    @property
    def turn_count(self) -> int:
        return len(self.turn_node_ids)


@dataclass
class ProcedureGraph:
    nodes: Dict[str, Node]
    edges: List[Edge]
    start_node_id: str
    terminal_node_ids: List[str]

    def successors(self, node_id: str) -> List[Edge]:
        return [e for e in self.edges if e.source_id == node_id]

    def get_node(self, node_id: str) -> Optional[Node]:
        return self.nodes.get(node_id)

    def is_terminal(self, node_id: str) -> bool:
        return node_id in self.terminal_node_ids

    def is_hub(self, node_id: str) -> bool:
        node = self.nodes.get(node_id)
        return node is not None and node.is_decision_hub


def build_sdet_graph() -> ProcedureGraph:
    nodes: Dict[str, Node] = {}

    def n(id, name, role, template_id, is_hub=False, desc=""):
        node = Node(id=id, name=name, role=role, prompt_template_id=template_id,
                    is_decision_hub=is_hub, description=desc)
        nodes[id] = node
        return node

    n("N0", "Open", NodeRole.AGENT, "open")
    n("N1", "UserRequest", NodeRole.USER, "user_request")
    n("N2", "ParseRequirement", NodeRole.AGENT, "parse_requirement")
    n("N3", "ClarifyHub", NodeRole.AGENT, "clarify_hub", is_hub=True,
      desc="Routes: clear -> N5, needs_clarification -> N4, abandon -> T_ABANDON")
    n("N4", "ClarifyDetails", NodeRole.USER, "clarify_details")
    n("N5", "DetermineIntent", NodeRole.AGENT, "determine_intent")
    n("N6", "IntentHub", NodeRole.AGENT, "intent_hub", is_hub=True,
      desc="Routes: positive/negative/edge/error/permission -> N7")
    n("N7", "IdentifyJourney", NodeRole.AGENT, "identify_journey")
    n("N8", "FeatureHub", NodeRole.AGENT, "feature_hub", is_hub=True,
      desc="Routes: auth/form/CRUD/nav/data_display/search/payment/notification/media -> N9")
    n("N9", "IdentifyElements", NodeRole.AGENT, "identify_elements")
    n("N10", "DetermineLocators", NodeRole.AGENT, "determine_locators")
    n("N11", "PlanActions", NodeRole.AGENT, "plan_actions")
    n("N12", "DesignAssertions", NodeRole.AGENT, "design_assertions")
    n("N13", "AddReliability", NodeRole.AGENT, "add_reliability")
    n("N14", "GenerateCode", NodeRole.AGENT, "generate_code")
    n("N15", "ReviewHub", NodeRole.AGENT, "review_hub", is_hub=True,
      desc="Routes: accept -> T_SUCCESS, revise -> N7, abandon -> T_ABANDON")

    terminal_ids = ["T_SUCCESS", "T_ABANDON", "T_ESCALATE"]
    for tid in terminal_ids:
        nodes[tid] = Node(id=tid, name=tid[2:].title(), role=NodeRole.TERMINAL, prompt_template_id="")

    edges: List[Edge] = [
        Edge("N0", "N1"),
        Edge("N1", "N2"),
        Edge("N2", "N3"),
        Edge("N3", "N5", "requirement_clear"),
        Edge("N3", "N4", "needs_clarification"),
        Edge("N3", "T_ABANDON", "abandon_request"),
        Edge("N4", "N2"),
        Edge("N5", "N6"),
        Edge("N6", "N7", "positive"),
        Edge("N6", "N7", "negative"),
        Edge("N6", "N7", "edge"),
        Edge("N6", "N7", "error_handling"),
        Edge("N6", "N7", "permission"),
        Edge("N7", "N8"),
        Edge("N8", "N9", "auth"),
        Edge("N8", "N9", "form"),
        Edge("N8", "N9", "crud"),
        Edge("N8", "N9", "navigation"),
        Edge("N8", "N9", "data_display"),
        Edge("N8", "N9", "search"),
        Edge("N8", "N9", "payment"),
        Edge("N8", "N9", "notification"),
        Edge("N8", "N9", "media"),
        Edge("N9", "N10"),
        Edge("N10", "N11"),
        Edge("N11", "N12"),
        Edge("N12", "N13"),
        Edge("N13", "N14"),
        Edge("N14", "N15"),
        Edge("N15", "T_SUCCESS", "accept"),
        Edge("N15", "N7", "revise"),
        Edge("N15", "T_ABANDON", "abandon_request"),
    ]

    return ProcedureGraph(
        nodes=nodes,
        edges=edges,
        start_node_id="N0",
        terminal_node_ids=terminal_ids,
    )


def enumerate_paths(graph: ProcedureGraph, max_turns: int = 35) -> List[Path]:
    """Enumerate a handful of representative structural paths (for analysis)."""
    paths: List[Path] = []

    def dfs(current: str, visited: List[str], edges_taken: List[Edge], hub: Dict[str, str]):
        if graph.is_terminal(current):
            paths.append(Path(node_ids=list(visited), hub_decisions=dict(hub), edges_taken=list(edges_taken)))
            return
        succ = graph.successors(current)
        if not succ or len(visited) > max_turns:
            paths.append(Path(node_ids=list(visited), hub_decisions=dict(hub), edges_taken=list(edges_taken)))
            return
        for edge in succ:
            if edge.target_id in visited and visited.count(edge.target_id) > 2:
                continue
            if graph.get_node(current) and graph.get_node(current).is_decision_hub:
                hub[current] = edge.condition_label
            visited.append(current)
            edges_taken.append(edge)
            dfs(edge.target_id, visited, edges_taken, hub)
            edges_taken.pop()
            visited.pop()
            if graph.get_node(current) and graph.get_node(current).is_decision_hub:
                hub.pop(current, None)

    dfs(graph.start_node_id, [], [], {})
    return [p for p in paths if p.node_ids and graph.is_terminal(p.node_ids[-1])]
