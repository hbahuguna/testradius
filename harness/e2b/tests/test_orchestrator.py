"""Tests for STORY-E2B-006.1 — End-to-End Orchestration."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from harness.e2b.orchestrator import E2BOrchestrationOptions, E2BOrchestrator
from harness.execution.base import BaseExecutor, ExecutionResult, ExecutionStatus, ExecutorConfig


class FakeExecutor(BaseExecutor):
    def __init__(self, config: ExecutorConfig, *, fail: bool = False, raise_on_execute: bool = False):
        super().__init__(config)
        self.fail = fail
        self.raise_on_execute = raise_on_execute
        self.prepared = False
        self.cleaned = False
        self.executed = False

    def prepare(self) -> bool:
        self.prepared = True
        self.status = ExecutionStatus.PREPARING
        return True

    def execute_plan(self) -> ExecutionResult:
        self.executed = True
        run_dir = Path(self.config.artifacts_dir) / self.config.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        # Simulate 004.1 artifacts
        (run_dir / "manifest.json").write_text(json.dumps({
            "run_id": self.config.run_id,
            "artifacts": [{"type": "screenshot", "path": f"artifacts/{self.config.run_id}/shot.png", "filename": "shot.png"}],
        }))
        (run_dir / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (run_dir / "step_results.json").write_text(json.dumps({"steps": [{"step_id": "S1", "intent": "Open page", "status": "PASSED"}]}))
        if self.raise_on_execute:
            raise RuntimeError("sandbox crashed")
        status = ExecutionStatus.FAILED if self.fail else ExecutionStatus.COMPLETED
        return ExecutionResult(
            run_id=self.config.run_id,
            status=status,
            started_at="t0",
            ended_at="t1",
            error="failed step" if self.fail else None,
            metadata={"executor": "fake-e2b", "sandbox_id": "sbx-fake"},
            summary={"total_steps": 1, "passed_steps": 0 if self.fail else 1, "failed_steps": 1 if self.fail else 0},
        )

    def get_status(self) -> ExecutionStatus:
        return self.status

    def stop(self) -> bool:
        self.cleaned = True
        return True

    def cleanup(self) -> bool:
        self.cleaned = True
        return True


def test_orchestrator_coordinates_steps_and_tracks_progress(tmp_path):
    events = []
    opts = E2BOrchestrationOptions(
        run_id="r1", target_url="https://testradius.dev", plan={"plan_id": "P1", "steps": [{"step_id": "S1"}]},
        artifacts_dir=tmp_path, enable_vision=False, enable_bug_review=False,
    )
    ex = FakeExecutor(ExecutorConfig(run_id="r1", target_url="https://x", plan=opts.plan, artifacts_dir=tmp_path))
    orch = E2BOrchestrator(executor=ex, progress_callback=events.append)
    report = orch.run(opts)

    assert report.status == "COMPLETED"
    assert ex.prepared and ex.executed and ex.cleaned
    stages = [e["stage"] for e in events]
    assert "init" in stages and "execute" in stages and "cleanup" in stages and "orchestration" in stages
    assert report.execution["status"] == "COMPLETED"
    assert (tmp_path / "r1" / "orchestration_report.json").exists()
    assert report.artifacts["manifest"]


def test_orchestrator_cleans_up_on_execution_failure(tmp_path):
    ex = FakeExecutor(ExecutorConfig(run_id="r2", target_url="https://x", plan={}, artifacts_dir=tmp_path), fail=True)
    orch = E2BOrchestrator(executor=ex)
    opts = E2BOrchestrationOptions(
        run_id="r2", target_url="https://x", plan={"steps": []}, artifacts_dir=tmp_path,
        enable_vision=False, enable_bug_review=False,
    )
    report = orch.run(opts)
    assert report.status == "FAILED"
    assert ex.cleaned is True
    assert report.execution["error"] == "failed step"
    assert any(e["stage"] == "cleanup" and e["status"] == "completed" for e in report.progress)


def test_orchestrator_cleans_up_on_exception(tmp_path):
    ex = FakeExecutor(ExecutorConfig(run_id="r3", target_url="https://x", plan={}, artifacts_dir=tmp_path), raise_on_execute=True)
    orch = E2BOrchestrator(executor=ex)
    opts = E2BOrchestrationOptions(run_id="r3", target_url="https://x", plan={"steps": []}, artifacts_dir=tmp_path)
    report = orch.run(opts)
    assert report.status in {"FAILED", "TIMEOUT", "STOPPED"}
    assert ex.cleaned is True
    assert report.errors
    assert (tmp_path / "r3" / "orchestration_report.json").exists()


def test_orchestrator_vision_and_bug_review_mock(tmp_path):
    ex = FakeExecutor(ExecutorConfig(run_id="r4", target_url="https://testradius.dev", plan={}, artifacts_dir=tmp_path))
    # force actionable finding via injected inspector
    class FakeInspector:
        def inspect(self, screenshot, **ctx):
            return {
                "screenshot": screenshot, "rounds": [{"round": 1, "purpose": "initial", "findings": []}],
                "deduped": [{"category": "overlap", "issue": "CTA overlaps text", "severity": "high", "confidence": 0.9, "description": "x", "location": "hero"}],
                "summary": {"actionable_deduped_findings": 1, "round_count": 1},
            }
    orch = E2BOrchestrator(executor=ex, inspector=FakeInspector())
    opts = E2BOrchestrationOptions(
        run_id="r4", target_url="https://testradius.dev", plan={"plan_id": "P", "steps": [{"step_id": "S1"}]},
        artifacts_dir=tmp_path, enable_vision=True, enable_bug_review=True, vision_rounds=1,
    )
    report = orch.run(opts)
    assert report.status == "COMPLETED"
    assert report.vision and report.vision["summary"]["total_actionable_findings"] == 1
    assert report.bug_review and report.bug_review["actionable_findings"] == 1
    assert (tmp_path / "r4" / "vision_inspection_report.json").exists()
    assert (tmp_path / "r4" / "bug_review_package.json").exists()
    # approval required - no filing performed by orchestrator
    assert "status" not in (report.bug_review or {}) or report.bug_review.get("status") != "filed"


def test_orchestrator_loads_plan_from_file(tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"plan_id": "PFILE", "steps": [{"step_id": "S1"}]}))
    ex = FakeExecutor(ExecutorConfig(run_id="r5", target_url="https://x", plan={}, artifacts_dir=tmp_path))
    orch = E2BOrchestrator(executor=ex)
    report = orch.run(E2BOrchestrationOptions(run_id="r5", target_url="https://x", plan=plan_path, artifacts_dir=tmp_path, enable_vision=False, enable_bug_review=False))
    assert report.status == "COMPLETED"
    assert ex.config.plan["plan_id"] == "PFILE"
