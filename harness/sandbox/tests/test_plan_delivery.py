"""Unit tests for compiled plan and runtime config delivery to sandboxes."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.execution.base import ExecutionStatus, ExecutorConfig
from harness.execution.e2b import E2BExecutor
from harness.sandbox.base import BaseSandboxProvider
from harness.sandbox.delivery import (
    RuntimeConfig,
    SandboxDeliveryResult,
    SecretExposureError,
    deliver_plan_and_config,
    verify_delivered_files,
)


class MockSandboxProvider(BaseSandboxProvider):
    """In-memory mock sandbox provider for delivery tests."""

    def __init__(self):
        self.files: dict[tuple[str, str], bytes] = {}
        self.commands: list[str] = []

    def create(self, template: str = "base", timeout: int = 300, **kwargs) -> str:
        return "sbx-test-123"

    def kill(self, sandbox_id: str) -> bool:
        return True

    def run_command(self, sandbox_id: str, command: str, timeout: int = 60) -> dict:
        self.commands.append(command)
        # Handle verification command: test -s '<path>' && echo OK
        if "test -s" in command:
            # extract path
            path = command.split("'")[1]
            if (sandbox_id, path) in self.files and len(self.files[(sandbox_id, path)]) > 0:
                return {"stdout": "OK", "stderr": "", "exit_code": 0}
            return {"stdout": "", "stderr": "No such file", "exit_code": 1}
        return {"stdout": "done", "stderr": "", "exit_code": 0}

    def upload_file(self, sandbox_id: str, path: str, content: bytes) -> bool:
        self.files[(sandbox_id, path)] = content
        return True

    def download_file(self, sandbox_id: str, path: str) -> bytes:
        return self.files.get((sandbox_id, path), b"")

    def is_running(self, sandbox_id: str) -> bool:
        return True


@pytest.fixture
def sample_compiled_plan() -> dict:
    return {
        "schema_version": "1.0",
        "plan_id": "PLAN-SMOKE-001",
        "title": "Smoke Test for TestRadius Landing Page",
        "objective": "Verify navigation and primary CTA",
        "sut": {
            "base_url": "https://testradius.dev",
            "environment": "staging",
            "viewport": "1280x800",
        },
        "preconditions": ["Browser launched", "Network available"],
        "cases": [
            {
                "case_id": "TC-01",
                "title": "Homepage Load",
                "steps": [
                    {
                        "step_id": "S1",
                        "ordinal": 1,
                        "intent": "Navigate to landing page",
                        "action_type": "navigate",
                        "target": {"description": "Homepage URL"},
                        "success_criteria": ["Title is visible"],
                    }
                ],
            }
        ],
    }


@pytest.fixture
def sample_runtime_config() -> RuntimeConfig:
    return RuntimeConfig(
        run_id="run-test-456",
        target_url="https://testradius.dev",
        env="staging",
        allowed_domains=["testradius.dev"],
        env_vars={"BASE_URL": "https://testradius.dev"},
        timeout_s=300,
        metadata={"suite": "smoke"},
    )


def test_deliver_plan_and_config_success(sample_compiled_plan, sample_runtime_config):
    provider = MockSandboxProvider()
    res = deliver_plan_and_config(
        provider=provider,
        sandbox_id="sbx-test-123",
        plan=sample_compiled_plan,
        runtime_config=sample_runtime_config,
        destination_dir="/home/user",
        verify=True,
    )

    assert isinstance(res, SandboxDeliveryResult)
    assert res.sandbox_id == "sbx-test-123"
    assert res.plan_path == "/home/user/compiled_test_plan.json"
    assert res.config_path == "/home/user/runtime_config.json"
    assert res.verified is True
    assert res.plan_bytes > 0
    assert res.config_bytes > 0
    assert res.plan_id == "PLAN-SMOKE-001"

    # Verify files stored in mock provider
    uploaded_plan = json.loads(provider.files[("sbx-test-123", "/home/user/compiled_test_plan.json")].decode("utf-8"))
    uploaded_cfg = json.loads(provider.files[("sbx-test-123", "/home/user/runtime_config.json")].decode("utf-8"))
    uploaded_legacy = json.loads(provider.files[("sbx-test-123", "/home/user/plan.json")].decode("utf-8"))

    assert uploaded_plan["plan_id"] == "PLAN-SMOKE-001"
    assert uploaded_cfg["run_id"] == "run-test-456"
    assert uploaded_cfg["target_url"] == "https://testradius.dev"
    assert uploaded_legacy["plan_id"] == "PLAN-SMOKE-001"


def test_deliver_plan_from_file_path(tmp_path, sample_compiled_plan, sample_runtime_config):
    plan_file = tmp_path / "sample_plan.json"
    plan_file.write_text(json.dumps(sample_compiled_plan))

    provider = MockSandboxProvider()
    res = deliver_plan_and_config(
        provider=provider,
        sandbox_id="sbx-test-123",
        plan=plan_file,
        runtime_config=sample_runtime_config,
    )

    assert res.verified is True
    assert res.plan_id == "PLAN-SMOKE-001"


def test_deliver_plan_from_json_string(sample_compiled_plan, sample_runtime_config):
    plan_str = json.dumps(sample_compiled_plan)
    provider = MockSandboxProvider()
    res = deliver_plan_and_config(
        provider=provider,
        sandbox_id="sbx-test-123",
        plan=plan_str,
        runtime_config=sample_runtime_config,
    )

    assert res.verified is True
    assert res.plan_id == "PLAN-SMOKE-001"


def test_secret_exposure_strict_mode(sample_compiled_plan, sample_runtime_config):
    # Inject a raw AWS key into test data
    bad_plan = dict(sample_compiled_plan)
    bad_plan["test_data"] = {"leaked_key": "AKIA1234567890ABCDEF"}

    provider = MockSandboxProvider()
    with pytest.raises(SecretExposureError) as exc_info:
        deliver_plan_and_config(
            provider=provider,
            sandbox_id="sbx-test-123",
            plan=bad_plan,
            runtime_config=sample_runtime_config,
            strict_secrets=True,
        )

    assert "Potential raw secrets detected" in str(exc_info.value)
    assert "aws" in str(exc_info.value)


def test_secret_exposure_auto_redact(sample_compiled_plan, sample_runtime_config):
    bad_plan = dict(sample_compiled_plan)
    bad_plan["notes"] = "Use Bearer secret_token_value_12345 for testing"

    provider = MockSandboxProvider()
    res = deliver_plan_and_config(
        provider=provider,
        sandbox_id="sbx-test-123",
        plan=bad_plan,
        runtime_config=sample_runtime_config,
        strict_secrets=False,
    )

    assert res.verified is True
    uploaded_text = provider.files[("sbx-test-123", "/home/user/compiled_test_plan.json")].decode("utf-8")
    assert "[REDACTED]" in uploaded_text
    assert "secret_token_value_12345" not in uploaded_text


def test_upload_failure(sample_compiled_plan, sample_runtime_config):
    provider = MockSandboxProvider()
    provider.upload_file = MagicMock(return_value=False)

    with pytest.raises(RuntimeError) as exc_info:
        deliver_plan_and_config(
            provider=provider,
            sandbox_id="sbx-test-123",
            plan=sample_compiled_plan,
            runtime_config=sample_runtime_config,
        )

    assert "Failed to upload" in str(exc_info.value)


def test_verify_delivered_files_check(sample_compiled_plan, sample_runtime_config):
    provider = MockSandboxProvider()
    provider.upload_file("sbx-test-123", "/home/user/test.json", b'{"ok": true}')

    assert verify_delivered_files(provider, "sbx-test-123", ["/home/user/test.json"]) is True
    assert verify_delivered_files(provider, "sbx-test-123", ["/home/user/missing.json"]) is False


def test_e2b_executor_uses_plan_delivery(sample_compiled_plan):
    provider = MockSandboxProvider()

    cfg = ExecutorConfig(
        run_id="run-e2b-delivery-001",
        target_url="https://testradius.dev",
        plan=sample_compiled_plan,
        metadata={"env": "staging", "allowed_domains": ["testradius.dev"]},
    )

    executor = E2BExecutor(cfg)
    executor.provider = provider
    executor.sandbox_id = "sbx-test-123"

    # Mock script run
    provider.run_command = MagicMock(return_value={"stdout": "Example Domain", "stderr": "", "exit_code": 0})
    provider.download_file = MagicMock(return_value=b"fake-png-bytes")

    res = executor.execute_plan()
    assert res.status == ExecutionStatus.COMPLETED
    assert hasattr(executor, "delivery_result")
    assert executor.delivery_result.verified is True
    assert executor.delivery_result.plan_path == "/home/user/compiled_test_plan.json"
    assert executor.delivery_result.config_path == "/home/user/runtime_config.json"

    # Confirm files were uploaded
    assert ("sbx-test-123", "/home/user/compiled_test_plan.json") in provider.files
    assert ("sbx-test-123", "/home/user/runtime_config.json") in provider.files
