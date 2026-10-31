"""Tests for Cloud Room client core."""
import os
from harness.integrations.cloudroom import CloudRoomClient, CloudRoomError


def test_client_requires_token(monkeypatch):
    monkeypatch.delenv("CLOUDROOM_TOKEN", raising=False)
    monkeypatch.delenv("CLOUDROOM_API_TOKEN", raising=False)
    try:
        CloudRoomClient()
        assert False, "Should have raised"
    except CloudRoomError as e:
        assert "CLOUDROOM_TOKEN required" in str(e)


def test_client_with_token(monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    client = CloudRoomClient()
    assert client.token == "test-token"
    assert client.base_url == "http://127.0.0.1:9840"


def test_client_custom_url(monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    monkeypatch.setenv("CLOUDROOM_URL", "http://localhost:9999/")
    client = CloudRoomClient()
    assert client.base_url == "http://localhost:9999"


def test_generate_request_id(monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    client = CloudRoomClient()
    rid = client._generate_request_id()
    assert len(rid) == 16
    assert all(c.isalnum() or c in "_-" for c in rid)


def test_headers(monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    client = CloudRoomClient()
    h = client._headers("req123")
    assert h["Authorization"] == "Bearer test-token"
    assert h["Content-Type"] == "application/json"
    assert h["X-Request-ID"] == "req123"
