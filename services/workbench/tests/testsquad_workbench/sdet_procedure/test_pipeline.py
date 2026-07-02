import json
import pytest

from testsquad_workbench.sdet_procedure.graph import build_sdet_graph, enumerate_paths
from testsquad_workbench.sdet_procedure.scenario import ScenarioSampler
from testsquad_workbench.sdet_procedure.pipeline import (
    LLMClient,
    ConversationTurn,
    GeneratedConversation,
    generate_conversation,
    run_pipeline,
)


class TestLLMClient:
    def test_generate_returns_string(self):
        llm = LLMClient()
        result = llm.generate("system prompt", "instruction")
        assert isinstance(result, str)
        assert result.startswith("[Simulated")


class TestConversationTurn:
    def test_to_dict(self):
        turn = ConversationTurn(role="assistant", content="hello", node_id="N0")
        d = turn.to_dict()
        assert d == {"role": "assistant", "content": "hello"}


class TestGeneratedConversation:
    def test_to_messages(self):
        conv = GeneratedConversation(
            turns=[
                ConversationTurn(role="assistant", content="hi", node_id="N0"),
                ConversationTurn(role="user", content="test", node_id="N1"),
            ],
            path=None,
            scenario=None,
        )
        msgs = conv.to_messages()
        assert len(msgs) == 2
        assert msgs[0] == {"role": "assistant", "content": "hi"}

    def test_to_training_format(self):
        from testsquad_workbench.sdet_procedure.scenario import (
            ScenarioVariables, FeatureType, TestType, PageType, UserStyle, Complexity,
        )
        graph = build_sdet_graph()
        paths = enumerate_paths(graph)
        path = paths[0]
        scenario = ScenarioVariables(
            feature_type=FeatureType.AUTH,
            test_type=TestType.POSITIVE,
            page_type=PageType.SINGLE_PAGE,
            user_style=UserStyle.SPECIFIC,
            complexity=Complexity.SIMPLE,
        )
        conv = GeneratedConversation(
            turns=[
                ConversationTurn(role="assistant", content="hi", node_id="N0"),
            ],
            path=path,
            scenario=scenario,
        )
        tf = conv.to_training_format()
        assert "messages" in tf
        assert "metadata" in tf
        assert tf["metadata"]["path_nodes"] == path.node_ids
        assert tf["metadata"]["hub_decisions"] == path.hub_decisions


class TestGenerateConversation:
    def test_generates_turns_for_path(self):
        graph = build_sdet_graph()
        paths = enumerate_paths(graph)
        sampler = ScenarioSampler(seed=42)
        llm = LLMClient()
        for path in paths[:3]:
            scenario = sampler.sample()
            conv = generate_conversation(graph, path, scenario, llm)
            assert isinstance(conv, GeneratedConversation)
            assert len(conv.turns) > 0
            assert conv.path is path
            assert conv.scenario is scenario

    def test_skips_terminal_nodes(self):
        graph = build_sdet_graph()
        paths = enumerate_paths(graph)
        llm = LLMClient()
        sampler = ScenarioSampler(seed=42)
        accept_paths = [p for p in paths if p.hub_decisions.get("N15") == "accept"]
        conv = generate_conversation(graph, accept_paths[0], sampler.sample(), llm)
        turn_node_ids = [t.node_id for t in conv.turns]
        assert "T_SUCCESS" not in turn_node_ids
        assert "T_ABANDON" not in turn_node_ids

    def test_alternates_roles(self):
        graph = build_sdet_graph()
        paths = enumerate_paths(graph)
        llm = LLMClient()
        sampler = ScenarioSampler(seed=42)
        accept_paths = [p for p in paths if p.hub_decisions.get("N15") == "accept"]
        assert len(accept_paths) > 0, "No accept paths found"
        conv = generate_conversation(graph, accept_paths[0], sampler.sample(), llm)
        roles = [t.role for t in conv.turns]
        assert "assistant" in roles
        assert "user" in roles


class TestRunPipeline:
    def test_run_pipeline_with_mock(self, tmp_path):
        output = tmp_path / "test_output.jsonl"
        llm = LLMClient()
        convs = run_pipeline(
            llm=llm,
            n_paths=3,
            n_per_path=2,
            output_path=str(output),
            seed=42,
        )
        assert len(convs) == 6

        with open(output) as f:
            lines = f.readlines()
        assert len(lines) == 6

        data = json.loads(lines[0])
        assert "messages" in data
        assert "metadata" in data
        assert len(data["messages"]) > 0
