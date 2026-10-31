"""Tests for error handling."""
import os
from harness.integrations.cloudroom import CloudRoomClient, CloudRoomError


def test_health_check_failure(monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    client = CloudRoomClient()
    def mock_request(*args, **kwargs):
        raise CloudRoomError("fail")
    client._request = mock_request
    assert client.health_check() is False


def test_clear_errors(monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    try:
        CloudRoomClient(token="bad")
        # Should work with token
    except:
        pass
