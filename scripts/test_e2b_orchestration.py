#!/usr/bin/env python3
"""Demo for STORY-E2B-006.1: End-to-End E2B Orchestration.

Coordinates plan -> E2B execution (mocked executor for safe demo) -> artifact
collection -> vision inspection -> bug review package -> orchestration report,
with progress tracking and cleanup.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.e2b.orchestrator import E2BOrchestrationOptions, E2BOrchestrator
from harness.execution.base import BaseExecutor, ExecutionResult, ExecutionStatus, ExecutorConfig


class DemoE2BExecutor(BaseExecutor):
    """Mock executor that simulates E2B execution and artifact production."""

    def __init__(self, config: ExecutorConfig):
        super().__init__(config)
        self.cleaned = False

    def prepare(self) -> bool:
        self.status = ExecutionStatus.PREPARING
        return True

    def execute_plan(self) -> ExecutionResult:
        run_dir = Path(self.config.artifacts_dir) / self.config.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "STEP-01.png").write_bytes(b"\x89PNG\r\n\x1a\n(demo)")
        (run_dir / "manifest.json").write_text(json.dumps({
            "run_id": self.config.run_id,
            "source": {"provider": "DemoE2BProvider", "sandbox_id": "sbx-demo-0061"},
            "artifacts": [{"type": "screenshot", "path": f"artifacts/{self.config.run_id}/STEP-01.png", "filename": "STEP-01.png"}],
        }, indent=2))
        (run_dir / "step_results.json").write_text(json.dumps({
            "plan_id": self.config.plan.get("plan_id"),
            "status": "PASSED",
            "steps": [{"step_id": "S1", "intent": "Navigate and verify homepage", "status": "PASSED"}],
        }, indent=2))
        self.status = ExecutionStatus.COMPLETED
        return ExecutionResult(
            run_id=self.config.run_id, status=ExecutionStatus.COMPLETED,
            started_at="t0", ended_at="t1", duration_ms=500,
            metadata={"executor": "e2b-demo", "sandbox_id": "sbx-demo-0061"},
            summary={"total_steps": 1, "passed_steps": 1, "failed_steps": 0},
            screenshots=[run_dir / "STEP-01.png"],
        )

    def get_status(self) -> ExecutionStatus:
        return self.status

    def stop(self) -> bool:
        self.cleaned = True
        return True

    def cleanup(self) -> bool:
        self.cleaned = True
        return True


class DemoInspector:
    def inspect(self, screenshot, **ctx):
        return {
            "screenshot": screenshot,
            "rounds": [{"round": 1, "purpose": "initial_inspection", "findings": [{"category": "layout", "issue": "none", "severity": "info", "confidence": 0.9}]}],
            "deduped": [{"category": "layout", "issue": "none", "severity": "info", "confidence": 0.9, "description": "No layout issue"}],
            "summary": {"round_count": 1, "total_findings": 1, "deduped_findings": 1, "actionable_deduped_findings": 0},
        }


def main() -> None:
    artifacts = Path("artifacts/demo_e2b_orchestration")
    run_id = "run-e2b-orch-demo"
    plan = {"plan_id": "PLAN-ORCH", "title": "E2B orchestration demo", "steps": [{"step_id": "S1", "intent": "Open homepage", "action_type": "navigate"}]}
    events = []

    print("=" * 72)
    print("STORY-E2B-006.1: End-to-End Orchestration")
    print("=" * 72)
    orch = E2BOrchestrator(
        executor_factory=DemoE2BExecutor,
        inspector=DemoInspector(),
        progress_callback=lambda e: (events.append(e), print(f"  [{e['status']}] {e['stage']}: {e['detail']}")),
    )
    report = orch.run(E2BOrchestrationOptions(
        run_id=run_id, target_url="https://testradius.dev", plan=plan,
        artifacts_dir=artifacts, enable_vision=True, enable_bug_review=True, vision_rounds=1,
    ))
    report_path = artifacts / run_id / "orchestration_report.json"
    print("\nReport:", json.dumps({"run_id": report.run_id, "status": report.status, "stages": [e["stage"] for e in events], "execution_status": (report.execution or {}).get("status"), "vision_screenshots": (report.vision or {}).get("screenshots_analyzed"), "report_path": str(report_path)}, indent=2))
    assert report.status == "COMPLETED"
    assert report_path.exists()
    assert any(e["stage"] == "cleanup" and e["status"] == "completed" for e in events)
    assert report.execution and report.execution["status"] == "COMPLETED"
    assert report.vision is not None
    print("\n✓ 006.1 demo passed: orchestration coordinated execute->vision->report with progress tracking and cleanup.")
    print("=" * 72)


if __name__ == "__main__":
    main()
