from __future__ import annotations

import asyncio

import pytest

from cell.agent.mcp import (
    FakeMCPClient,
    MCPDenied,
    MCPError,
    ToolRegistry,
)


def test_allowlisted_tool_runs_and_is_audited():
    async def scenario():
        client = FakeMCPClient()
        registry = ToolRegistry(client)
        result = await registry.call(
            "executor",
            "browser.navigate",
            {"url": "http://aut/"},
            ["file:public/index.html"],
        )
        assert result.ok
        assert client.calls == [("browser.navigate", {"url": "http://aut/"})]
        assert registry.calls[0]["citations"] == ["file:public/index.html"]

    asyncio.run(scenario())


def test_denied_tool_fails_before_client_call():
    async def scenario():
        client = FakeMCPClient()
        registry = ToolRegistry(client)
        with pytest.raises(MCPDenied, match="tool_not_allowed"):
            await registry.call("executor", "browser.shell", {}, ["file:x"])
        assert client.calls == []
        assert registry.denials[-1]["reason"] == "tool_not_allowed"

    asyncio.run(scenario())


def test_citation_is_required_before_tool_call():
    async def scenario():
        client = FakeMCPClient()
        registry = ToolRegistry(client)
        with pytest.raises(MCPDenied, match="citation_required"):
            await registry.call("executor", "browser.navigate", {"url": "http://aut/"}, [])
        assert client.calls == []

    asyncio.run(scenario())


class SlowClient(FakeMCPClient):
    async def call_tool(self, name, arguments):
        await asyncio.sleep(0.05)
        return await super().call_tool(name, arguments)


def test_tool_timeout_is_typed():
    async def scenario():
        registry = ToolRegistry(SlowClient(), timeout_seconds=0.005)
        with pytest.raises(MCPError, match="timed out") as exc:
            await registry.call("executor", "browser.navigate", {}, ["file:x"])
        assert exc.value.kind == "tool_timeout"

    asyncio.run(scenario())


def test_unknown_tool_is_denied_before_invocation():
    async def scenario():
        client = FakeMCPClient()
        registry = ToolRegistry(client, allowed_by_role={"executor": ["browser.unknown"]})
        with pytest.raises(MCPDenied, match="tool_not_registered"):
            await registry.call("executor", "browser.unknown", {}, ["file:x"])
        assert client.calls == []

    asyncio.run(scenario())


def test_unhealthy_server_is_not_selected():
    async def scenario():
        client = FakeMCPClient(healthy=False)
        registry = ToolRegistry(client, health_ttl_seconds=0)
        with pytest.raises(MCPError, match="unhealthy") as exc:
            await registry.call("executor", "browser.navigate", {}, ["file:x"])
        assert exc.value.kind == "tool_unavailable"
        assert client.calls == []
        assert registry.health_checks == [False]

    asyncio.run(scenario())


def test_health_is_cached_within_the_ttl():
    async def scenario():
        client = FakeMCPClient()
        registry = ToolRegistry(client, health_ttl_seconds=60)
        await registry.call("executor", "browser.navigate", {}, ["file:x"])
        client.healthy = False
        await registry.call("executor", "browser.navigate", {}, ["file:x"])
        assert registry.health_checks == [True]

    asyncio.run(scenario())


def test_policy_allowlist_filters_the_tool_list():
    async def scenario():
        registry = ToolRegistry(
            FakeMCPClient(),
            allowed_by_role={"executor": ["browser.navigate"]},
        )
        tools = await registry.list_tools("executor")
        assert [tool.name for tool in tools] == ["browser.navigate"]

    asyncio.run(scenario())
