"""Tests for subagent orchestration."""
import os
from harness.integrations.cloudroom import CloudRoomClient, SubagentOrchestrator


def test_spawn_parallel(monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    client = CloudRoomClient()
    count = [0]
    def mock_spawn(session_id, prompt=None, model=None, **kwargs):
        count[0] += 1
        return {"thread_id": f"t{count[0]}"}
    client.spawn_subagent = mock_spawn
    orch = SubagentOrchestrator(client)
    res = orch.spawn_parallel("cr_1", ["p1", "p2"], models=["m1", "m2"])
    assert len(res) == 2
    assert res[0]["status"] == "RUNNING"
    assert res[1]["thread_id"] == "t2"
