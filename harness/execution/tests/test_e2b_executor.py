"""Unit tests for E2BExecutor with compiled plans and Playwright generation."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.execution.base import ExecutionStatus, ExecutorConfig
from harness.execution.e2b import E2BExecutor
from harness.sandbox.base import BaseSandboxProvider


class MockE2BProvider(BaseSandboxProvider):
    def __init__(self):
        self.files: dict[tuple[str, str], bytes] = {}
        self.commands: list[str] = []
        self.created_template = None

    def create(self, template: str = "playwright-chromium", timeout: int = 300, **kwargs) -> str:
        self.created_template = template
        return "sbx-e2b-456"

    def kill(self, sandbox_id: str) -> bool:
        return True

    def run_command(self, sandbox_id: str, command: str, timeout: int = 60) -> dict:
        self.commands.append(command)
        if "echo READY" in command:
            return {"stdout": "READY", "stderr": "", "exit_code": 0}
        if "test -s" in command:
            path = command.split("'")[1]
            if (sandbox_id, path) in self.files:
                return {"stdout": "OK", "stderr": "", "exit_code": 0}
            return {"stdout": "", "stderr": "Not found", "exit_code": 1}
        # Simulate test runner output
        return {
            "stdout": "RESULTS_FILE=/home/user/artifacts/step_results.json\nOVERALL_STATUS=PASSED\nPASSED=2/2",
            "stderr": "",
            "exit_code": 0,
        }

    def upload_file(self, sandbox_id: str, path: str, content: bytes) -> bool:
        self.files[(sandbox_id, path)] = content
        return True

    def download_file(self, sandbox_id: str, path: str) -> bytes:
        return self.files.get((sandbox_id, path), b"")

    def is_running(self, sandbox_id: str) -> bool:
        return True


@pytest.fixture
def sample_plan() -> dict:
    return {
        "schema_version": "1.0",
        "plan_id": "PLAN-E2B-EXEC-01",
        "title": "Smoke Execution Plan",
        "sut": {"base_url": "https://testradius.dev"},
        "cases": [
            {
                "case_id": "TC-01",
                "title": "Smoke Case",
                "steps": [
                    {
                        "step_id": "S1",
                        "ordinal": 1,
                        "intent": "Navigate to landing",
                        "action_type": "navigate",
                        "input": {"url": "https://testradius.dev"},
                    },
                    {
                        "step_id": "S2",
                        "ordinal": 2,
                        "intent": "Verify page header",
                        "action_type": "assert",
                        "success_criteria": ["Title is visible"],
                    },
                ],
            }
        ],
    }


def test_e2b_executor_prepare(sample_plan):
    provider = MockE2BProvider()
    cfg = ExecutorConfig(
        run_id="run-prep-001",
        target_url="https://testradius.dev",
        plan=sample_plan,
        metadata={"template": "playwright-chromium"},
    )
    executor = E2BExecutor(cfg)
    executor.provider = provider

    ok = executor.prepare()
    assert ok is True
    assert executor.sandbox_id == "sbx-e2b-456"
    assert provider.created_template == "playwright-chromium"
    assert executor.status == ExecutionStatus.PREPARING


def test_e2b_executor_execute_plan_success(tmp_path, sample_plan):
    provider = MockE2BProvider()

    # Pre-populate step results that script would generate in sandbox
    mock_results = {
        "plan_id": "PLAN-E2B-EXEC-01",
        "status": "PASSED",
        "total_steps": 2,
        "passed_steps": 2,
        "failed_steps": 0,
        "steps": [
            {
                "step_id": "S1",
                "case_id": "TC-01",
                "intent": "Navigate to landing",
                "action_type": "navigate",
                "status": "PASSED",
                "duration_ms": 350,
                "screenshot": "/home/user/artifacts/S1.png",
                "error": None,
            },
            {
                "step_id": "S2",
                "case_id": "TC-01",
                "intent": "Verify page header",
                "action_type": "assert",
                "status": "PASSED",
                "duration_ms": 120,
                "screenshot": "/home/user/artifacts/S2.png",
                "error": None,
            },
        ],
    }

    # Put mock artifacts in sandbox
    provider.files[("sbx-e2b-456", "/home/user/artifacts/step_results.json")] = json.dumps(mock_results).encode("utf-8")
    provider.files[("sbx-e2b-456", "/home/user/artifacts/S1.png")] = b"fake-png-s1"
    provider.files[("sbx-e2b-456", "/home/user/artifacts/S2.png")] = b"fake-png-s2"
    provider.files[("sbx-e2b-456", "/home/user/artifacts/trace.zip")] = b"fake-trace-zip"

    cfg = ExecutorConfig(
        run_id="run-exec-001",
        target_url="https://testradius.dev",
        plan=sample_plan,
        artifacts_dir=tmp_path / "artifacts",
        capture_traces=True,
    )
    executor = E2BExecutor(cfg)
    executor.provider = provider

    res = executor.execute_plan()

    assert res.status == ExecutionStatus.COMPLETED
    assert len(res.steps) == 2
    assert res.steps[0].step_id == "S1"
    assert res.steps[0].status == "PASSED"
    assert res.steps[1].step_id == "S2"
    assert res.steps[1].status == "PASSED"

    # Verify script was generated from plan and uploaded
    assert ("sbx-e2b-456", "/home/user/test_script.py") in provider.files
    script_content = provider.files[("sbx-e2b-456", "/home/user/test_script.py")].decode("utf-8")
    assert "PLAN-E2B-EXEC-01" in script_content
    assert "async_playwright" in script_content

    # Verify run command uses python3 and PLAYWRIGHT_BROWSERS_PATH
    run_cmd = [c for c in provider.commands if "test_script.py" in c][0]
    assert "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" in run_cmd
    assert "python3 /home/user/test_script.py" in run_cmd
    assert "cd /app" not in run_cmd

    # Verify local downloaded artifacts
    run_artifacts_dir = tmp_path / "artifacts" / "run-exec-001"
    assert (run_artifacts_dir / "S1.png").read_bytes() == b"fake-png-s1"
    assert (run_artifacts_dir / "S2.png").read_bytes() == b"fake-png-s2"
    assert (run_artifacts_dir / "trace.zip").read_bytes() == b"fake-trace-zip"
    assert res.trace_path == run_artifacts_dir / "trace.zip"
    assert len(res.screenshots) == 2
