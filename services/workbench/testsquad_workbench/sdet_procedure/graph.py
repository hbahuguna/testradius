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

    def __repr__(self) -> str:
        hub_info = ", ".join(
            f"{nid}={dec}" for nid, dec in self.hub_decisions.items()
        )
        return (
            f"Path({self.turn_count} turns, "
            f"nodes={' → '.join(self.node_ids)}, "
            f"hubs=[{hub_info}])"
        )


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

    def n(
        id: str,
        name: str,
        role: NodeRole,
        template_id: str,
        is_hub: bool = False,
        desc: str = "",
    ) -> Node:
        node = Node(
            id=id,
            name=name,
            role=role,
            prompt_template_id=template_id,
            is_decision_hub=is_hub,
            description=desc,
        )
        nodes[id] = node
        return node

    n("N0", "Open", NodeRole.AGENT, "open")
    n("N1", "UserRequest", NodeRole.USER, "user_request")
    n("N2", "ParseRequirement", NodeRole.AGENT, "parse_requirement")
    n(
        "N3",
        "ClarifyHub",
        NodeRole.AGENT,
        "clarify_hub",
        is_hub=True,
        desc="Routes: clear → N5, needs_clarification → N4, abandon → T_ABANDON",
    )
    n("N4", "ClarifyDetails", NodeRole.USER, "clarify_details")
    n("N5", "DetermineIntent", NodeRole.AGENT, "determine_intent")
    n(
        "N6",
        "IntentHub",
        NodeRole.AGENT,
        "intent_hub",
        is_hub=True,
        desc="Routes: positive/negative/edge/error/permission → N7 (context only)",
    )
    n("N7", "IdentifyJourney", NodeRole.AGENT, "identify_journey")
    n(
        "N8",
        "FeatureHub",
        NodeRole.AGENT,
        "feature_hub",
        is_hub=True,
        desc="Routes: auth/form/CRUD/nav/data_display/search/payment/notification/media → N9 (context only)",
    )
    n("N9", "IdentifyElements", NodeRole.AGENT, "identify_elements")
    n("N10", "DetermineLocators", NodeRole.AGENT, "determine_locators")
    n("N11", "PlanActions", NodeRole.AGENT, "plan_actions")
    n("N12", "DesignAssertions", NodeRole.AGENT, "design_assertions")
    n("N13", "AddReliability", NodeRole.AGENT, "add_reliability")
    n("N14", "GenerateCode", NodeRole.AGENT, "generate_code")
    n(
        "N15",
        "ReviewHub",
        NodeRole.AGENT,
        "review_hub",
        is_hub=True,
        desc="Routes: accept → T_SUCCESS, revise → N7, abandon → T_ABANDON",
    )

    terminal_ids = ["T_SUCCESS", "T_ABANDON", "T_ESCALATE"]
    for tid in terminal_ids:
        nodes[tid] = Node(
            id=tid,
            name=tid[2:].title(),
            role=NodeRole.TERMINAL,
            prompt_template_id="",
        )

    edges: List[Edge] = [
        # Main flow
        Edge("N0", "N1", "", "Agent opens, user responds"),
        Edge("N1", "N2", "", "User request, agent parses"),
        Edge("N2", "N3", "", "Agent finishes parsing, routes to clarify hub"),
        Edge("N3", "N5", "requirement_clear", "Requirement is clear, proceed"),
        Edge("N3", "N4", "needs_clarification", "Need more details from user"),
        Edge("N3", "T_ABANDON", "abandon_request", "User abandons request"),
        Edge("N4", "N2", "", "User provides clarification, agent re-parses"),
        Edge("N5", "N6", "", "Intent determined, routes to intent hub"),
        Edge("N6", "N7", "positive", "Positive test path"),
        Edge("N6", "N7", "negative", "Negative test path"),
        Edge("N6", "N7", "edge", "Edge case test path"),
        Edge("N6", "N7", "error_handling", "Error handling test path"),
        Edge("N6", "N7", "permission", "Permission test path"),
        Edge("N7", "N8", "", "Journey identified, routes to feature hub"),
        Edge("N8", "N9", "auth", "Authentication feature"),
        Edge("N8", "N9", "form", "Form feature"),
        Edge("N8", "N9", "crud", "CRUD feature"),
        Edge("N8", "N9", "navigation", "Navigation feature"),
        Edge("N8", "N9", "data_display", "Data display feature"),
        Edge("N8", "N9", "search", "Search feature"),
        Edge("N8", "N9", "payment", "Payment feature"),
        Edge("N8", "N9", "notification", "Notification feature"),
        Edge("N8", "N9", "media", "Media feature"),
        Edge("N9", "N10", "", "Elements identified, determine locators"),
        Edge("N10", "N11", "", "Locators determined, plan actions"),
        Edge("N11", "N12", "", "Actions planned, design assertions"),
        Edge("N12", "N13", "", "Assertions designed, add reliability"),
        Edge("N13", "N14", "", "Reliability added, generate code"),
        Edge("N14", "N15", "", "Code generated, route to review hub"),
        Edge("N15", "T_SUCCESS", "accept", "User accepts generated test"),
        Edge("N15", "N7", "revise", "User requests revision, re-identify journey"),
        Edge("N15", "T_ABANDON", "abandon_request", "User abandons"),
    ]

    return ProcedureGraph(
        nodes=nodes,
        edges=edges,
        start_node_id="N0",
        terminal_node_ids=terminal_ids,
    )


_CLARIFY_LOOP_NODES = {"N3", "N4", "N2"}
_REVISE_LOOP_ENTRY = "N7"
_REVISE_HUB = "N15"
_CLARIFY_HUB = "N3"

_MAX_CLARIFY_ITERATIONS = 2
_MAX_REVISE_ITERATIONS = 2
_MAX_TOTAL_TURNS = 35


def enumerate_paths(
    graph: ProcedureGraph,
    max_clarify: int = _MAX_CLARIFY_ITERATIONS,
    max_revise: int = _MAX_REVISE_ITERATIONS,
    max_turns: int = _MAX_TOTAL_TURNS,
) -> List[Path]:
    visited: List[str] = []
    hub_decisions: Dict[str, str] = {}
    edges_taken: List[Edge] = []
    paths: List[Path] = []

    def clarify_loop_count() -> int:
        return visited.count(_CLARIFY_HUB)

    def revise_loop_count() -> int:
        return visited.count(_REVISE_HUB) - 1  # first visit isn't a revision

    def is_valid_hub_choice(hub_id: str, edge: Edge) -> bool:
        if hub_id == _CLARIFY_HUB:
            if edge.condition_label == "needs_clarification":
                if clarify_loop_count() >= max_clarify:
                    return False
            if clarify_loop_count() >= max_clarify + 1:
                return False
        if hub_id == _REVISE_HUB:
            if edge.condition_label == "revise":
                if revise_loop_count() >= max_revise:
                    return False
        return True

    def dfs(current_id: str) -> None:
        node = graph.get_node(current_id)
        if node is None:
            return

        visited.append(current_id)

        if graph.is_terminal(current_id):
            paths.append(
                Path(
                    node_ids=list(visited),
                    hub_decisions=dict(hub_decisions),
                    edges_taken=list(edges_taken),
                )
            )
            visited.pop()
            return

        succ_edges = graph.successors(current_id)
        if not succ_edges:
            paths.append(
                Path(
                    node_ids=list(visited),
                    hub_decisions=dict(hub_decisions),
                    edges_taken=list(edges_taken),
                )
            )
            visited.pop()
            return

        found_any = False
        for edge in succ_edges:
            if visited.count(edge.target_id) > 2:
                continue

            if (
                edge.target_id in ("N4", "N2")
                and edge.target_id not in _CLARIFY_LOOP_NODES
            ):
                if visited.count("N4") >= 2:
                    continue

            if node and node.is_decision_hub:
                if not is_valid_hub_choice(current_id, edge):
                    continue

            turn_count = len(
                [nid for nid in visited if not graph.is_terminal(nid)]
            )
            if turn_count > max_turns:
                continue

            if node and node.is_decision_hub:
                hub_decisions[current_id] = edge.condition_label
            edges_taken.append(edge)
            found_any = True
            dfs(edge.target_id)
            edges_taken.pop()
            if node and node.is_decision_hub:
                hub_decisions.pop(current_id, None)

        if not found_any:
            paths.append(
                Path(
                    node_ids=list(visited),
                    hub_decisions=dict(hub_decisions),
                    edges_taken=list(edges_taken),
                )
            )

        visited.pop()

    dfs(graph.start_node_id)

    valid_paths = []
    for p in paths:
        if p.node_ids and graph.is_terminal(p.node_ids[-1]):
            valid_paths.append(p)

    return valid_paths


def path_variant_key(path: Path) -> Tuple[int, str, int, str]:
    """Sort key: clarify iterations, clarify outcome, revise iterations, revise outcome."""
    clarify_visits = [
        i
        for i, nid in enumerate(path.node_ids)
        if nid == _CLARIFY_HUB
    ]
    c_iter = max(0, len(clarify_visits) - 1)
    c_outcome = path.hub_decisions.get("N3", "none")

    revise_visits = [
        i
        for i, nid in enumerate(path.node_ids)
        if nid == _REVISE_HUB
    ]
    r_iter = max(0, len(revise_visits) - 1)
    r_outcome = path.hub_decisions.get("N15", "accept")

    final = path.node_ids[-1] if path.node_ids else ""
    return (c_iter, c_outcome, r_iter, r_outcome, final)
