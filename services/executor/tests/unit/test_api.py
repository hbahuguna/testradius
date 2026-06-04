import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, AsyncMock, patch
from testsquad_shared.models import RunStatus
from src.main import app, get_sandbox

client = TestClient(app)

@pytest.fixture
def mock_sandbox():
    mock = MagicMock()
    # create_run is async, so we use AsyncMock for it
    mock.create_run = AsyncMock()
    app.dependency_overrides[get_sandbox] = lambda: mock
    yield mock
    app.dependency_overrides.clear()

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_create_run_api(mock_sandbox):
    mock_sandbox.create_run.return_value = RunStatus(
        run_id="run-123",
        status="RUNNING"
    )
    
    payload = {
        "repo_url": "https://github.com/test",
        "command": "ls",
        "trace_id": "trace-456"
    }
    
    response = client.post("/runs", json=payload)
    assert response.status_code == 200
    assert response.json()["run_id"] == "run-123"
    assert response.json()["status"] == "RUNNING"

def test_get_run_status_api(mock_sandbox):
    mock_sandbox.get_run_status.return_value = RunStatus(
        run_id="run-123",
        status="COMPLETED"
    )
    
    response = client.get("/runs/run-123")
    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"
