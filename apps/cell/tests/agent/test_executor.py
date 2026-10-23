from __future__ import annotations

import asyncio

import pytest

from cell.agent.citations import CitationError, CitationResolver
from cell.agent.context import ContextNode, StaticContextClient
from cell.agent.executor import AgentCancelled, Executor
from cell.agent.mcp import FakeMCPClient, ToolRegistry
from cell.agent.types import Citation, Plan, PlanStep, ToolResult


def context() -> StaticContextClient:
    return StaticContextClient(
        [ContextNode("file:public/index.html", "file", "public/index.html", "index")]
    )


def plan(*steps: PlanStep) -> Plan:
    return Plan(goal="checkout", steps=list(steps))


def step(tool: str, **arguments) -> PlanStep:
    return PlanStep(
        step_id=f"step-{tool}",
        intent=tool,
        tool=tool,
        arguments=arguments,
        citations=[Citation("file:public/index.html")],
    )


def make_executor(client: FakeMCPClient | None = None, *, block: bool = True):
    context_client = context()
    resolver = CitationResolver(context_client)
    registry = ToolRegistry(client or FakeMCPClient())
    return Executor(resolver, registry, block_on_a11y_violation=block), registry


def test_executor_completes_cited_steps():
    async def scenario():
        events = []
        client = FakeMCPClient()
        executor, _ = make_executor(client)
        result = await executor.execute(
            plan(
                step("browser.navigate", url="http://aut/"),
                step("browser.assert_text", text="Menu"),
            ),
            emit=lambda event_type, payload: events.append((event_type, payload)),
        )
        assert result.verdict == "passed"
        assert len(result.steps) == 2
        assert [event[1]["event"] for event in events if event[0] == "tool"] == [
            "tool.called",
            "tool.completed",
            "tool.called",
            "tool.completed",
        ]

    asyncio.run(scenario())


def test_blocking_a11y_violation_stops_and_is_terminal():
    async def scenario():
        events = []
        client = FakeMCPClient(
            a11y_violations=[{"tag": "button", "reason": "missing_accessible_name"}]
        )
        executor, _ = make_executor(client)
        result = await executor.execute(
            plan(
                step("browser.navigate", url="http://aut/"),
                step("browser.check_a11y"),
                step("browser.assert_text", text="Menu"),
            ),
            emit=lambda event_type, payload: events.append((event_type, payload)),
        )
        assert result.verdict == "testability_defect"
        assert [call[0] for call in client.calls] == ["browser.navigate", "browser.check_a11y"]
        assert any(event[1]["event"] == "a11y.blocked" for event in events if event[0] == "verdict")

    asyncio.run(scenario())


def test_tool_failure_stops_the_plan():
    async def scenario():
        client = FakeMCPClient(
            responses={
                "browser.assert_text": ToolResult(ok=False, error="text_not_found")
            }
        )
        executor, _ = make_executor(client)
        result = await executor.execute(
            plan(step("browser.assert_text", text="Missing"), step("browser.navigate", url="http://aut/"))
        )
        assert result.verdict == "failed"
        assert result.steps[-1].detail == "text_not_found"
        assert len(client.calls) == 1

    asyncio.run(scenario())


def test_uncited_step_is_rejected_before_execution():
    async def scenario():
        client = FakeMCPClient()
        executor, _ = make_executor(client)
        uncited = PlanStep(step_id="s1", intent="open", tool="browser.navigate", arguments={})
        with pytest.raises(CitationError):
            await executor.execute(plan(uncited))
        assert client.calls == []

    asyncio.run(scenario())


def test_cancellation_is_checked_between_steps():
    async def scenario():
        client = FakeMCPClient()
        executor, _ = make_executor(client)
        with pytest.raises(AgentCancelled):
            await executor.execute(
                plan(step("browser.navigate", url="http://aut/")),
                is_cancelled=lambda: True,
            )

    asyncio.run(scenario())


def test_repeated_identical_tool_call_is_detected():
    async def scenario():
        events = []
        client = FakeMCPClient()
        executor, _ = make_executor(client)
        repeat = step("browser.navigate", url="http://aut/")
        result = await executor.execute(
            plan(repeat, repeat, repeat),
            emit=lambda event_type, payload: events.append((event_type, payload)),
        )
        assert result.verdict == "failed"
        assert result.reason == "LoopDetected"
        assert len(client.calls) == 2
        assert any(
            event[1].get("event") == "loop.detected" for event in events if event[0] == "verdict"
        )

    asyncio.run(scenario())


def test_step_events_include_action_observation_and_usage():
    async def scenario():
        events = []
        executor, _ = make_executor()
        await executor.execute(
            plan(step("browser.navigate", url="http://aut/")),
            emit=lambda event_type, payload: events.append((event_type, payload)),
        )
        completed = [
            payload
            for event_type, payload in events
            if event_type == "step" and payload.get("event") == "step.completed"
        ][0]
        assert completed["thought"]
        assert completed["action"] == "browser.navigate"
        assert completed["args"] == {"url": "http://aut/"}
        assert completed["observation"] == "ok"
        assert completed["usage"]["total_tokens"] == 0

    asyncio.run(scenario())
