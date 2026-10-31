"""Tests for LocalPlaywrightExecutor."""
from harness.execution import LocalPlaywrightExecutor, ExecutorConfig, ExecutionStatus
from pathlib import Path


def test_local_executor_instantiation(tmp_path):
    config = ExecutorConfig(
        run_id="r1",
        target_url="https://example.com",
        plan={"testCases": []},
        artifacts_dir=tmp_path,
    )
    executor = LocalPlaywrightExecutor(config)
    assert executor.status == ExecutionStatus.PENDING
    assert executor.get_status() == ExecutionStatus.PENDING
    assert executor.is_running() is False
    assert executor.is_complete() is False


def test_local_executor_interface(tmp_path):
    config = ExecutorConfig(
        run_id="r2",
        target_url="https://example.com",
        plan={"testCases": [{"id": "TC1", "title": "Test"}]},
        artifacts_dir=tmp_path,
    )
    executor = LocalPlaywrightExecutor(config)
    assert hasattr(executor, "prepare")
    assert hasattr(executor, "execute_plan")
    assert hasattr(executor, "get_status")
    assert hasattr(executor, "stop")
    assert hasattr(executor, "cleanup")
    assert executor.cleanup() is True
