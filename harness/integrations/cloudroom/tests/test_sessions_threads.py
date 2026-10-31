"""Tests for sessions and threads API."""
import os
from harness.integrations.cloudroom import CloudRoomClient


def test_create_session_generates_id(monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    client = CloudRoomClient()
    # Mock the request
    original = client._request
    calls = []
    def mock_request(method, path, **kwargs):
        calls.append((method, path))
        return {"session_id": "cr_demo123", "status": "created"}
    client._request = mock_request
    resp = client.create_session(request_id="demo123")
    assert resp["session_id"].startswith("cr_")
    assert calls[0][0] == "POST"
    assert calls[0][1] == "/v1/sessions"


def test_create_thread(monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    client = CloudRoomClient()
    original = client._request
    calls = []
    def mock_request(method, path, json_data=None, **kwargs):
        calls.append((method, path, json_data))
        return {"thread_id": "t1", "status": "created"}
    client._request = mock_request
    resp = client.create_thread("cr_demo", prompt="test prompt")
    assert resp["thread_id"] == "t1"
    assert calls[0][0] == "POST"
    assert "/threads" in calls[0][1]


def test_spawn_subagent(monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    client = CloudRoomClient()
    def mock_request(method, path, **kwargs):
        return {"thread_id": "st1", "status": "created"}
    client._request = mock_request
    resp = client.spawn_subagent("cr_demo", prompt="subtask")
    assert resp["thread_id"] == "st1"
