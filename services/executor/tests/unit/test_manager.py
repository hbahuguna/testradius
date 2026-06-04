import pytest
from unittest.mock import MagicMock, patch, ANY
from testsquad_shared.models import RunRequest
from testsquad_executor.sandbox.manager import SandboxManager

@pytest.fixture
def mock_docker():
    with patch("docker.from_env") as mock:
        yield mock

def test_sandbox_manager_init(mock_docker):
    # Should check network and image
    manager = SandboxManager()
    mock_docker.return_value.networks.get.assert_called_with("testsquad-sandbox")
    mock_docker.return_value.images.get.assert_called_with("testsquad-worker:latest")

@pytest.mark.anyio
async def test_create_run_with_volumes(mock_docker):
    manager = SandboxManager()
    request = RunRequest(
        repo_url="https://github.com/test/repo",
        command="pytest",
        trace_id="trace-123"
    )
    
    mock_container = MagicMock()
    mock_docker.return_value.containers.run.return_value = mock_container
    
    status = await manager.create_run(request)
    
    assert status.status == "RUNNING"
    assert mock_docker.return_value.containers.run.called
    args, kwargs = mock_docker.return_value.containers.run.call_args
    
    # Verify volumes are mounted
    assert "volumes" in kwargs
    assert len(kwargs["volumes"]) == 1
    # Key is a temp path, value is bind config
    for host_path, config in kwargs["volumes"].items():
        assert "/app" == config["bind"]
        assert "rw" == config["mode"]

def test_get_run_status_exited(mock_docker):
    manager = SandboxManager()
    mock_container = MagicMock()
    mock_container.status = "exited"
    mock_container.attrs = {'State': {'ExitCode': 0}}
    mock_docker.return_value.containers.get.return_value = mock_container
    
    status = manager.get_run_status("some-id")
    assert status.status == "COMPLETED"
    assert status.exit_code == 0

def test_get_run_status_failed(mock_docker):
    manager = SandboxManager()
    mock_container = MagicMock()
    mock_container.status = "exited"
    mock_container.attrs = {'State': {'ExitCode': 1}}
    mock_docker.return_value.containers.get.return_value = mock_container
    
    status = manager.get_run_status("some-id")
    assert status.status == "FAILED"
    assert status.exit_code == 1
