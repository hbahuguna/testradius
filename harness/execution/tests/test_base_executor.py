"""Tests for BaseExecutor interface."""
from pathlib import Path
from harness.execution import (
    BaseExecutor,
    ExecutionResult,
    ExecutionStatus,
    ExecutorConfig,
    StepResult,
)


def test_execution_status_enum():
    assert ExecutionStatus.PENDING.value == "PENDING"
    assert ExecutionStatus.RUNNING.value == "RUNNING"
    assert ExecutionStatus.COMPLETED.value == "COMPLETED"
    assert ExecutionStatus.FAILED.value == "FAILED"


def test_step_result_creation():
    step = StepResult(
        step_id="s1",
        test_case_id="TC1",
        title="Navigate to homepage",
        status="COMPLETED",
    )
    assert step.step_id == "s1"
    assert step.test_case_id == "TC1"
    assert step.screenshots == []
    assert step.assertions == []


def test_executor_config_defaults(tmp_path):
    config = ExecutorConfig(
        run_id="r1",
        target_url="https://example.com",
        plan={"testCases": []},
        artifacts_dir=tmp_path,
    )
    assert config.run_id == "r1"
    assert config.timeout_seconds == 600
    assert config.headless is True
    assert config.record_video is True


def test_execution_result_to_dict(tmp_path):
    result = ExecutionResult(
        run_id="r1",
        status=ExecutionStatus.COMPLETED,
        started_at="2026-01-01T00:00:00Z",
        ended_at="2026-01-01T00:01:00Z",
        duration_ms=60000,
        evidence_dir=tmp_path,
        screenshots=[tmp_path / "s1.png"],
    )
    d = result.to_dict()
    assert d["run_id"] == "r1"
    assert d["status"] == "COMPLETED"
    assert d["duration_ms"] == 60000
    assert len(d["screenshots"]) == 1


class DummyExecutor(BaseExecutor):
    def prepare(self) -> bool:
        self.status = ExecutionStatus.PREPARING
        return True

    def execute_plan(self) -> ExecutionResult:
        self.status = ExecutionStatus.RUNNING
        result = ExecutionResult(
            run_id=self.config.run_id,
            status=ExecutionStatus.COMPLETED,
            started_at="2026-01-01T00:00:00Z",
        )
        self._result = result
        self.status = ExecutionStatus.COMPLETED
        return result

    def get_status(self) -> ExecutionStatus:
        return self.status

    def stop(self) -> bool:
        self.status = ExecutionStatus.STOPPED
        return True

    def cleanup(self) -> bool:
        return True


def test_base_executor_interface(tmp_path):
    config = ExecutorConfig(
        run_id="r1",
        target_url="https://example.com",
        plan={"testCases": []},
        artifacts_dir=tmp_path,
    )
    executor = DummyExecutor(config)
    assert executor.status == ExecutionStatus.PENDING
    assert executor.prepare() is True
    assert executor.get_status() == ExecutionStatus.PREPARING
    result = executor.execute_plan()
    assert result.status == ExecutionStatus.COMPLETED
    assert executor.is_complete() is True
    assert executor.stop() is True
    assert executor.cleanup() is True
