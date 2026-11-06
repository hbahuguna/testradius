import json
from pathlib import Path

import pytest

from harness.checkpoints import ApprovalRegistry
from harness.computer_use.integration import ComputerUseHarnessRunner, PlanCheckpoint, build_findings_from_run, normalize_artifacts
from harness.connectors import GitHubConnector
from harness.execution.base import ExecutorConfig
from harness.execution.factory import ExecutorFactory

GOLDEN = Path(__file__).resolve().parents[3] / "evals" / "fixtures" / "compiled_test_plan.valid.json"


def load_golden() -> dict:
    return json.loads(GOLDEN.read_text())


def test_factory_creates_computer_use_executor_for_both_names():
    for et in ("gemini_computer_use", "compiled_plan"):
        cfg = ExecutorConfig(run_id="r1", target_url="https://testradius.dev", plan=load_golden(), artifacts_dir="artifacts", metadata={"mock": True})
        ex = ExecutorFactory.create_executor(cfg, et)
        assert type(ex).__name__ == "ComputerUseExecutor"


def test_executor_mock_produces_normalized_artifacts(tmp_path: Path):
    cfg = ExecutorConfig(run_id="run-exec-1", target_url="https://testradius.dev", plan=load_golden(), artifacts_dir=tmp_path, metadata={"mock": True, "mode": "local_spike"})
    ex = ExecutorFactory.create_executor(cfg, "gemini_computer_use")
    result = ex.execute_plan()
    assert result.status.value in {"COMPLETED", "FAILED"}
    assert (tmp_path / "run-exec-1" / "action_trace.jsonl").exists()
    assert (tmp_path / "run-exec-1" / "run_summary.json").exists()
    assert (tmp_path / "run-exec-1" / "step_results.json").exists()
    assert (tmp_path / "run-exec-1" / "compiled_test_plan.json").exists()


def test_plan_checkpoint_blocks_prod_draft_until_approved(tmp_path: Path):
    cp = PlanCheckpoint()
    plan = load_golden()
    plan["quality_gate"]["review_status"] = "draft"
    blocked = cp.review(run_id="run-cp-1", plan=plan, mode="production", artifacts_dir=tmp_path)
    assert blocked["allowed"] is False
    assert (tmp_path / "run-cp-1" / "plan_checkpoint.json").exists()
    # Approved plan passes even in production
    plan["quality_gate"]["review_status"] = "approved"
    allowed = cp.review(run_id="run-cp-2", plan=plan, mode="production", artifacts_dir=tmp_path)
    assert allowed["allowed"] is True


def test_harness_runner_failing_step_yields_finding_and_bug_review(tmp_path: Path):
    runner = ComputerUseHarnessRunner(
        artifacts_dir=tmp_path,
        bug_workflow=None,
        registry=ApprovalRegistry(),
    )
    # Inject a failing mock: assess fails -> fail_product finding
    from harness.execution.factory import ExecutorFactory as EF
    from harness.execution.base import ExecutorConfig as EC

    plan = load_golden()
    meta = {"mock": True, "mode": "local_spike", "assess_pass": False}
    report = runner.run_compiled_plan(run_id="run-harness-1", plan=plan, mode="local_spike", metadata=meta)
    assert (tmp_path / "run-harness-1" / "manifest.json").exists()
    assert (tmp_path / "run-harness-1" / "run_report.json").exists()
    assert (tmp_path / "run-harness-1" / "checkpoint_log.json").exists()
    assert (tmp_path / "run-harness-1" / "findings.json").exists()
    findings = json.loads((tmp_path / "run-harness-1" / "findings.json").read_text())
    assert len(findings) >= 1
    f0 = findings[0]
    for key in ("step_id", "expected", "observed", "screenshots", "trace_excerpt", "source_refs"):
        assert key in f0
    assert f0["source_refs"]
    # Bug review prepared but NOT filed
    assert (tmp_path / "run-harness-1" / "bug_review_package.json").exists()
    assert report["bug_review"]["approved"] is False
    # Filing without approval must fail
    with pytest.raises(PermissionError):
        runner.bug_workflow.file_after_approval(approval_id=report["bug_review"]["approval_id"], run_dir=tmp_path / "run-harness-1")
    # After approval, dry-run file succeeds (draft ticket)
    runner.bug_workflow.approve(report["bug_review"]["approval_id"], actor="qa-lead", detail="reviewed")
    result = runner.bug_workflow.file_after_approval(
        approval_id=report["bug_review"]["approval_id"], actor="qa-lead", run_dir=tmp_path / "run-harness-1",
        connector=GitHubConnector(repo="org/repo", dry_run=True),
    )
    assert result["status"] in {"dry_run", "duplicate"}


def test_harness_runner_prod_blocks_draft_plan_without_execution(tmp_path: Path):
    runner = ComputerUseHarnessRunner(artifacts_dir=tmp_path)
    plan = load_golden()
    plan["quality_gate"]["review_status"] = "draft"
    report = runner.run_compiled_plan(run_id="run-blocked-plan", plan=plan, mode="production", metadata={"mock": True})
    assert report["status"] == "BLOCKED"
    assert not (tmp_path / "run-blocked-plan" / "action_trace.jsonl").exists()
