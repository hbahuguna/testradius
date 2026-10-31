"""Tests for commands and receipts."""
import os
import time
from harness.integrations.cloudroom import CloudRoomClient


def test_send_command(monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    client = CloudRoomClient()
    calls = []
    def mock_request(method, path, json_data=None, **kwargs):
        calls.append((method, path, json_data))
        return {"receipt_id": "r1", "status": "accepted"}
    client._request = mock_request
    resp = client.send_command("test.cmd", params={"x": 1})
    assert resp["receipt_id"] == "r1"
    assert calls[0][0] == "POST"
    assert calls[0][2]["command"] == "test.cmd"


def test_wait_for_receipt_completed(monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    client = CloudRoomClient()
    states = ["accepted", "delivered", "completed"]
    idx = [0]
    def mock_request(method, path, **kwargs):
        s = states[idx[0]] if idx[0] < len(states) else "completed"
        idx[0] += 1
        return {"receipt_id": "r1", "status": s}
    client._request = mock_request
    resp = client.wait_for_receipt("r1", timeout=10, poll_interval=0.01)
    assert resp["status"] == "completed"


def test_wait_for_receipt_failed(monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    client = CloudRoomClient()
    def mock_request(method, path, **kwargs):
        return {"receipt_id": "r1", "status": "failed", "error": "boom"}
    client._request = mock_request
    resp = client.wait_for_receipt("r1", timeout=10, poll_interval=0.01)
    assert resp["status"] == "failed"
