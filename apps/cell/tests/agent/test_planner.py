from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from cell.agent.citations import CitationError, CitationResolver
from cell.agent.context import ContextNode, StaticContextClient
from cell.agent.mcp import MCPTool
from cell.agent.planner import InsufficientContext, PlanError, Planner
from cell.agent.provider import AnthropicProvider, FakeProvider, OpenAICompatibleProvider
from cell.agent.types import Citation, Completion, PlanStep


def node() -> ContextNode:
    return ContextNode("file:public/index.html", "file", "public/index.html", "index")


def tools() -> list[MCPTool]:
    return [MCPTool("browser.navigate"), MCPTool("browser.assert_text")]


def plan_json(**overrides):
    step = {
        "step_id": "s1",
        "intent": "open the page",
        "tool": "browser.navigate",
        "arguments": {"url": "http://aut/"},
        "citations": ["file:public/index.html"],
    }
    step.update(overrides)
    return json.dumps({"steps": [step]})


def make_planner(text: str, context: StaticContextClient | None = None):
    context = context or StaticContextClient([node()])
    resolver = CitationResolver(context)
    provider = FakeProvider([Completion(text=text)], default=Completion(text=text))
    return Planner(provider, context, resolver)


def test_valid_plan_is_parsed_and_citations_are_resolved():
    async def scenario():
        planner = make_planner(plan_json())
        plan = await planner.plan("open checkout", tools=tools())
        assert plan.steps[0].step_id == "s1"
        assert plan.steps[0].citations[0].node_id == "file:public/index.html"

    asyncio.run(scenario())


def test_missing_citation_is_rejected():
    async def scenario():
        planner = make_planner(plan_json(citations=[]))
        with pytest.raises(PlanError, match="no citations") as exc:
            await planner.plan("open checkout", tools=tools())
        assert exc.value.code == "uncited_action"

    asyncio.run(scenario())


def test_unknown_citation_is_rejected():
    async def scenario():
        planner = make_planner(plan_json(citations=["file:missing"]))
        with pytest.raises(PlanError, match="unknown citation"):
            await planner.plan("open checkout", tools=tools())

    asyncio.run(scenario())


def test_unknown_tool_is_rejected():
    async def scenario():
        planner = make_planner(plan_json(tool="browser.shell"))
        with pytest.raises(PlanError, match="tool not available"):
            await planner.plan("open checkout", tools=tools())

    asyncio.run(scenario())


def test_dependency_cycle_is_rejected():
    async def scenario():
        payload = {
            "steps": [
                {
                    "step_id": "a",
                    "intent": "one",
                    "tool": "browser.navigate",
                    "arguments": {},
                    "citations": ["file:public/index.html"],
                    "depends_on": ["b"],
                },
                {
                    "step_id": "b",
                    "intent": "two",
                    "tool": "browser.navigate",
                    "arguments": {},
                    "citations": ["file:public/index.html"],
                    "depends_on": ["a"],
                },
            ]
        }
        planner = make_planner(json.dumps(payload))
        with pytest.raises(PlanError, match="cycle"):
            await planner.plan("open checkout", tools=tools())

    asyncio.run(scenario())


def test_empty_context_is_insufficient_context():
    async def scenario():
        planner = make_planner(plan_json(), StaticContextClient([]))
        with pytest.raises(InsufficientContext):
            await planner.plan("open checkout", tools=tools())

    asyncio.run(scenario())


def test_non_json_output_is_rejected():
    async def scenario():
        planner = make_planner("I would open the page.")
        with pytest.raises(PlanError, match="non-JSON"):
            await planner.plan("open checkout", tools=tools())

    asyncio.run(scenario())


def test_citation_resolver_rejects_empty_and_unknown():
    async def scenario():
        resolver = CitationResolver(StaticContextClient([node()]))
        with pytest.raises(CitationError):
            await resolver.resolve_all([])
        with pytest.raises(CitationError):
            await resolver.validate_step(
                PlanStep("s", "intent", None, citations=[Citation("file:nope")])
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("provider_factory", ["anthropic", "openai"])
def test_planner_runs_against_live_adapters_with_fake_transports(provider_factory):
    plan_text = plan_json()

    def anthropic_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "x-api-key" in request.headers
        assert body["messages"]
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": plan_text}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    def openai_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "Bearer" in request.headers.get("authorization", "")
        assert body["tools"]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": plan_text}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    async def scenario():
        context_client = StaticContextClient([node()])
        resolver = CitationResolver(context_client)
        if provider_factory == "anthropic":
            provider = AnthropicProvider("k", transport=httpx.MockTransport(anthropic_handler))
        else:
            provider = OpenAICompatibleProvider("k", transport=httpx.MockTransport(openai_handler))
        planner = Planner(provider, context_client, resolver)
        plan = await planner.plan("open checkout", tools=tools())
        assert plan.steps[0].tool == "browser.navigate"
        assert plan.steps[0].citations[0].node_id == "file:public/index.html"

    asyncio.run(scenario())
