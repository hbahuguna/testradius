"""Tests for artifacts and journal."""
import os
from harness.integrations.cloudroom import CloudRoomClient


def test_get_journal(monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    client = CloudRoomClient()
    def mock_request(method, path, **kwargs):
        return {"events": [{"type": "log", "msg": "hi"}]}
    client._request = mock_request
    resp = client.get_journal("cr_1")
    assert "events" in resp


def test_list_artifacts(monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    client = CloudRoomClient()
    def mock_request(method, path, **kwargs):
        return {"files": ["screenshot.png", "video.webm"]}
    client._request = mock_request
    resp = client.list_artifacts("cr_1")
    assert "files" in resp
