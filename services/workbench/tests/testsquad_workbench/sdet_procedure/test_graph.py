import pytest

from testsquad_workbench.sdet_procedure.graph import (
    NodeRole,
    Node,
    Edge,
    Path,
    ProcedureGraph,
    build_sdet_graph,
    enumerate_paths,
)


class TestGraphConstruction:
    def test_build_sdet_graph_returns_graph(self):
        graph = build_sdet_graph()
        assert isinstance(graph, ProcedureGraph)

    def test_graph_has_16_nodes(self):
        graph = build_sdet_graph()
        non_terminal = [n for nid, n in graph.nodes.items() if n.role != NodeRole.TERMINAL]
        assert len(non_terminal) == 16

    def test_graph_has_3_terminals(self):
        graph = build_sdet_graph()
        terminal = [n for nid, n in graph.nodes.items() if n.role == NodeRole.TERMINAL]
        assert len(terminal) == 3
        assert "T_SUCCESS" in graph.nodes
        assert "T_ABANDON" in graph.nodes
        assert "T_ESCALATE" in graph.nodes

    def test_start_node_is_N0(self):
        graph = build_sdet_graph()
        assert graph.start_node_id == "N0"

    def test_four_decision_hubs(self):
        graph = build_sdet_graph()
        hubs = [nid for nid, n in graph.nodes.items() if n.is_decision_hub]
        assert set(hubs) == {"N3", "N6", "N8", "N15"}

    def test_successors_return_edges(self):
        graph = build_sdet_graph()
        edges = graph.successors("N0")
        assert len(edges) == 1
        assert edges[0].target_id == "N1"

    def test_review_hub_has_three_outgoing(self):
        graph = build_sdet_graph()
        edges = graph.successors("N15")
        labels = {e.condition_label for e in edges}
        assert labels == {"accept", "revise", "abandon_request"}

    def test_is_terminal(self):
        graph = build_sdet_graph()
        assert graph.is_terminal("T_SUCCESS") is True
        assert graph.is_terminal("T_ABANDON") is True
        assert graph.is_terminal("N0") is False
        assert graph.is_terminal("N15") is False

    def test_is_hub(self):
        graph = build_sdet_graph()
        assert graph.is_hub("N3") is True
        assert graph.is_hub("N6") is True
        assert graph.is_hub("N0") is False
        assert graph.is_hub("N9") is False


class TestPathEnumeration:
    def test_enumerate_paths_returns_list(self):
        graph = build_sdet_graph()
        paths = enumerate_paths(graph)
        assert isinstance(paths, list)

    def test_all_paths_end_at_terminal(self):
        graph = build_sdet_graph()
        paths = enumerate_paths(graph)
        assert len(paths) > 0
        for p in paths:
            assert graph.is_terminal(p.node_ids[-1]), f"Path {p} does not end at terminal"

    def test_paths_contain_terminal_in_node_ids(self):
        graph = build_sdet_graph()
        paths = enumerate_paths(graph)
        for p in paths:
            terminal = p.node_ids[-1]
            assert terminal in ("T_SUCCESS", "T_ABANDON", "T_ESCALATE")

    def test_path_has_hub_decisions(self):
        graph = build_sdet_graph()
        paths = enumerate_paths(graph)
        accept_paths = [p for p in paths if p.hub_decisions.get("N15") == "accept"]
        assert len(accept_paths) > 0

    def test_turn_count_excludes_terminals(self):
        graph = build_sdet_graph()
        paths = enumerate_paths(graph)
        for p in paths:
            assert p.turn_count == len([n for n in p.node_ids if not graph.is_terminal(n)])
            assert p.turn_count <= 35

    def test_abandon_paths_exist(self):
        graph = build_sdet_graph()
        paths = enumerate_paths(graph)
        abandon = [p for p in paths if p.node_ids[-1] == "T_ABANDON"]
        assert len(abandon) > 0

    def test_success_paths_exist(self):
        graph = build_sdet_graph()
        paths = enumerate_paths(graph)
        success = [p for p in paths if p.node_ids[-1] == "T_SUCCESS"]
        assert len(success) > 0

    def test_path_exceeds_minimum_length(self):
        graph = build_sdet_graph()
        paths = enumerate_paths(graph)
        for p in paths:
            assert len(p.node_ids) >= 3

    def test_clarify_loop_respected(self):
        graph = build_sdet_graph()
        paths = enumerate_paths(graph, max_clarify=2)
        for p in paths:
            clarify_visits = [i for i, nid in enumerate(p.node_ids) if nid == "N3"]
            assert len(clarify_visits) <= 3

    def test_revise_loop_respected(self):
        graph = build_sdet_graph()
        paths = enumerate_paths(graph, max_revise=2)
        for p in paths:
            revise_visits = [i for i, nid in enumerate(p.node_ids) if nid == "N15"]
            assert len(revise_visits) <= 3

    def test_path_variant_key_is_sorted(self):
        from testsquad_workbench.sdet_procedure.graph import path_variant_key
        graph = build_sdet_graph()
        paths = enumerate_paths(graph)
        sorted_paths = sorted(paths, key=path_variant_key)
        keys = [path_variant_key(p) for p in sorted_paths]
        assert keys == sorted(keys), "path_variant_key should produce sortable keys"

    def test_turn_node_ids_excludes_terminals(self):
        path = Path(
            node_ids=["N0", "N1", "N2", "N3", "T_SUCCESS"],
            hub_decisions={"N3": "requirement_clear"},
            edges_taken=[],
        )
        turn_ids = path.turn_node_ids
        assert "T_SUCCESS" not in turn_ids
        assert "T_ABANDON" not in turn_ids
        assert "N0" in turn_ids


class TestDataclasses:
    def test_node_frozen(self):
        node = Node(id="N0", name="Open", role=NodeRole.AGENT, prompt_template_id="open")
        with pytest.raises(AttributeError):
            node.name = "Changed"

    def test_edge_frozen(self):
        edge = Edge(source_id="N0", target_id="N1")
        with pytest.raises(AttributeError):
            edge.source_id = "N2"

    def test_path_turn_count(self):
        path = Path(
            node_ids=["N0", "N1", "N2", "T_SUCCESS"],
            hub_decisions={},
            edges_taken=[],
        )
        assert path.turn_count == 3
