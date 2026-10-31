"""Tests for CloudRoomExecutor."""
import os
from pathlib import Path
from harness.execution import ExecutorConfig, ExecutionStatus
from harness.execution.cloudroom import CloudRoomExecutor


def test_cloudroom_executor_instantiation(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    config = ExecutorConfig(
        run_id="r1",
        target_url="https://example.com",
        plan={"testCases": []},
        artifacts_dir=tmp_path,
    )
    executor = CloudRoomExecutor(config)
    assert executor.status == ExecutionStatus.PENDING
    assert executor.get_status() == ExecutionStatus.PENDING
    assert executor.is_running() is False
    assert executor.is_complete() is False


def test_cloudroom_executor_interface(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    config = ExecutorConfig(
        run_id="r2",
        target_url="https://example.com",
        plan={"testCases": [{"id": "TC1", "title": "Test"}]},
        artifacts_dir=tmp_path,
    )
    executor = CloudRoomExecutor(config)
    assert hasattr(executor, "prepare")
    assert hasattr(executor, "execute_plan")
    assert hasattr(executor, "get_status")
    assert hasattr(executor, "stop")
    assert hasattr(executor, "cleanup")
    assert executor.cleanup() is True
