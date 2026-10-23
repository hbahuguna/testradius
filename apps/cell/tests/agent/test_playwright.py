from __future__ import annotations

import asyncio

import pytest

from cell.agent.playwright import PlaywrightMCPClient


class DummyPage:
    def get_by_test_id(self, value):
        return ("test_id", value)

    def get_by_role(self, role, *, name):
        return ("role", role, name)


def test_artifact_paths_are_run_scoped_and_cannot_escape(tmp_path):
    client = PlaywrightMCPClient(workspace_dir=str(tmp_path / "run_1"))
    path = client._artifact_path("evidence/cart.png", "cart.png")

    assert path == (tmp_path / "run_1" / "evidence" / "cart.png").resolve()
    with pytest.raises(ValueError, match="artifact_path_escape"):
        client._artifact_path("../cart.png", "cart.png")
    with pytest.raises(ValueError, match="artifact_path_escape"):
        client._artifact_path(str(tmp_path / "outside.png"), "cart.png")


def test_css_selector_fallback_is_blocked():
    client = PlaywrightMCPClient(workspace_dir="/tmp/run")
    with pytest.raises(ValueError, match="selector_fallback_blocked"):
        client._locator(DummyPage(), {"selector": "#checkout"})
    assert client._locator(DummyPage(), {"test_id": "checkout"}) == ("test_id", "checkout")
    assert client._locator(DummyPage(), {"role": "button", "name": "Buy"}) == (
        "role",
        "button",
        "Buy",
    )


def test_network_guard_denies_by_default_and_checks_the_allowlist():
    client = PlaywrightMCPClient(workspace_dir="/tmp/run")
    with pytest.raises(ValueError, match="network_egress_denied"):
        client._check_network("http://mock-aut:8080/")

    allowed = PlaywrightMCPClient(
        workspace_dir="/tmp/run",
        allow_network=True,
        allowed_hosts=["mock-aut"],
    )
    allowed._check_network("http://mock-aut:8080/")
    with pytest.raises(ValueError, match="host_not_allowed"):
        allowed._check_network("http://example.com/")


def test_closed_browser_is_unhealthy():
    async def scenario():
        client = PlaywrightMCPClient(workspace_dir="/tmp/run")
        assert await client.health() is True
        await client.close()
        assert await client.health() is False
        result = await client.call_tool("browser.navigate", {"url": "http://mock-aut/"})
        assert result.ok is False
        assert result.error == "browser_closed"

    asyncio.run(scenario())
