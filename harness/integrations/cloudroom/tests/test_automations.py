"""Tests for automations."""
import os
from harness.integrations.cloudroom import CloudRoomClient


def test_create_automation(monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    client = CloudRoomClient()
    def mock_request(method, path, json_data=None, **kwargs):
        return {"automation_id": "a1", "status": "created"}
    client._request = mock_request
    resp = client.create_automation(name="nightly", schedule="0 2 * * *")
    assert resp["automation_id"] == "a1"


def test_trigger_automation(monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    client = CloudRoomClient()
    def mock_request(method, path, **kwargs):
        return {"status": "triggered", "session_id": "cr_new"}
    client._request = mock_request
    resp = client.trigger_automation("a1")
    assert resp["status"] == "triggered"
