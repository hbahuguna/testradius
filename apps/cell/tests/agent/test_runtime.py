from __future__ import annotations

import asyncio
import json

from cell.agent.context import ContextNode, StaticContextClient
from cell.agent.mcp import FakeMCPClient, ToolRegistry
from cell.agent.provider import FakeProvider
from cell.agent.runtime import AgentSession
from cell.agent.types import Completion
from cell.models import Phase, RunStatus
from cell.runs.orchestrator import Orchestrator
from cell.runs.state import Run, RunStore

NODE = ContextNode("file:public/index.html", "file", "public/index.html", "index")


def plan_text(*, include_a11y: bool = False) -> str:
    steps = [
        {
            "step_id": "open",
            "intent": "open the fixture",
            "tool": "browser.navigate",
            "arguments": {"url": "http://aut/"},
            "citations": [NODE.node_id],
        }
    ]
    if include_a11y:
        steps.append(
            {
                "step_id": "a11y",
                "intent": "inspect accessible names",
                "tool": "browser.check_a11y",
                "arguments": {},
                "citations": [NODE.node_id],
            }
        )
    steps.append(
        {
            "step_id": "assert",
            "intent": "assert menu",
            "tool": "browser.assert_text",
            "arguments": {"text": "Menu"},
            "citations": [NODE.node_id],
        }
    )
    return json.dumps({"steps": steps})


def make_session(*, a11y: bool = False, plan: str | None = None, mcp=None) -> AgentSession:
    provider = FakeProvider([Completion(text=plan or plan_text(include_a11y=a11y))])
    context = StaticContextClient([NODE])
    registry = ToolRegistry(
        mcp
        or FakeMCPClient(
            a11y_violations=(
                [{"tag": "button", "reason": "missing_accessible_name"}] if a11y else []
            )
        )
    )
    return AgentSession(provider=provider, context=context, registry=registry)


async def run_to_completion(run: Run, session: AgentSession) -> Orchestrator:
    store = RunStore()
    store.create(run)
    orchestrator = Orchestrator(store, agent_factory=lambda _: session)
    orchestrator.start(run)
    for _ in range(300):
        await asyncio.sleep(0.01)
        if run.status in (
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.TIMED_OUT,
        ):
            return orchestrator
    raise AssertionError("run did not finish")


def test_agent_run_emits_plan_steps_and_passes():
    async def scenario():
        run = Run(
            run_id="run_agent",
            repo="fixture",
            commit="abc1234",
            scope="full",
            policy={"runtime": "agent", "provider": "fake"},
            goal="verify checkout",
        )
        orchestrator = await run_to_completion(run, make_session())
        events = orchestrator.get_events(run.run_id)
        assert run.status == RunStatus.SUCCEEDED
        assert run.phase == Phase.REPORT
        assert any(event["payload"].get("event") == "plan.created" for event in events)
        assert any(event["payload"].get("event") == "run.verdict" for event in events)
        assert any(event["payload"].get("event") == "run.completed" for event in events)

    asyncio.run(scenario())


def test_agent_run_blocks_on_a11y_defect_and_stops():
    async def scenario():
        run = Run(
            run_id="run_a11y",
            repo="fixture",
            commit="abc1234",
            scope="full",
            policy={"runtime": "agent", "provider": "fake"},
            goal="verify checkout",
        )
        orchestrator = await run_to_completion(run, make_session(a11y=True))
        events = orchestrator.get_events(run.run_id)
        assert run.status == RunStatus.FAILED
        assert run.phase == Phase.EXECUTE
        assert any(
            event["payload"].get("event") == "a11y.blocked" for event in events
        )
        assert not any(
            event["payload"].get("event") == "run.completed" for event in events
        )

    asyncio.run(scenario())


def test_agent_planner_failure_marks_run_failed():
    async def scenario():
        run = Run(
            run_id="run_plan_error",
            repo="fixture",
            commit="abc1234",
            scope="full",
            policy={"runtime": "agent", "provider": "fake"},
            goal="verify checkout",
        )
        orchestrator = await run_to_completion(run, make_session(plan="not json"))
        assert run.status == RunStatus.FAILED
        assert any(
            event["payload"].get("event") == "run.failed"
            for event in orchestrator.get_events(run.run_id)
        )

    asyncio.run(scenario())
