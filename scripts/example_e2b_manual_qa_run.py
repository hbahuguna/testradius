#!/usr/bin/env python3
"""Canonical E2B manual QA harness example.

Default mode is SAFE (mock/injected executor) so it runs without live E2B
credentials or sandboxes. Use --live only when the E2B environment is configured.

Examples:
  python3 scripts/example_e2b_manual_qa_run.py
  python3 scripts/example_e2b_manual_qa_run.py --target https://testradius.dev --run-id demo-e2b
  E2B_API_KEY=... E2B_DOMAIN=... EXECUTOR=e2b \
    python3 scripts/example_e2b_manual_qa_run.py --live
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.e2b.orchestrator import E2BOrchestrationOptions, E2BOrchestrator
from harness.execution.base import BaseExecutor, ExecutionResult, ExecutionStatus, ExecutorConfig


class MockE2BExecutor(BaseExecutor):
    """Safe demo executor that produces local artifacts and no live side effects."""

    def prepare(self) -> bool:
        self.status = ExecutionStatus.PREPARING
        return True

    def execute_plan(self) -> ExecutionResult:
        run_dir = Path(self.config.artifacts_dir) / self.config.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "STEP-01.png").write_bytes(b"\x89PNG\r\n\x1a\n(mock-e2b-example)")
        (run_dir / "step_results.json").write_text(json.dumps({
            "plan_id": (self.config.plan or {}).get("plan_id"),
            "status": "PASSED",
            "steps": [{"step_id": "S1", "status": "PASSED", "intent": "Open homepage"}],
        }, indent=2))
        (run_dir / "manifest.json").write_text(json.dumps({
            "run_id": self.config.run_id,
            "source": {"provider": "MockE2BExecutor", "sandbox_id": "sbx-mock-example"},
            "artifacts": [{"type": "screenshot", "path": str(run_dir / "STEP-01.png"), "filename": "STEP-01.png"}],
        }, indent=2))
        self.status = ExecutionStatus.COMPLETED
        return ExecutionResult(
            run_id=self.config.run_id,
            status=ExecutionStatus.COMPLETED,
            started_at="demo-start",
            ended_at="demo-end",
            duration_ms=250,
            metadata={"executor": "mock-e2b", "sandbox_id": "sbx-mock-example", "template": "playwright-chromium"},
            summary={"total_steps": 1, "passed_steps": 1, "failed_steps": 0},
            screenshots=[run_dir / "STEP-01.png"],
        )

    def get_status(self) -> ExecutionStatus:
        return self.status

    def stop(self) -> bool:
        return True

    def cleanup(self) -> bool:
        return True


class MockInspector:
    def inspect(self, screenshot, **ctx):
        return {
            "screenshot": screenshot,
            "summary": {"round_count": 1, "total_findings": 0, "deduped_findings": 0, "actionable_deduped_findings": 0},
            "deduped": [],
        }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--target", default="https://testradius.dev")
    p.add_argument("--run-id", default="run-e2b-example")
    p.add_argument("--artifacts-dir", default="artifacts/example_e2b_manual_qa")
    p.add_argument("--live", action="store_true", help="Use real executor factory (requires env config; environment-dependent)")
    args = p.parse_args()

    plan = {
        "plan_id": "PLAN-E2B-EXAMPLE",
        "title": "E2B manual QA example",
        "target": {"url": args.target},
        "steps": [{"step_id": "S1", "intent": "Open homepage and verify primary content", "action_type": "navigate"}],
        "metadata": {"template": "playwright-chromium"},
    }

    if args.live:
        if not os.environ.get("E2B_API_KEY") and (os.environ.get("EXECUTOR", "").lower() == "e2b" or os.environ.get("EXECUTOR_TYPE", "").lower() == "e2b"):
            print("ERROR: --live with E2B selected requires E2B_API_KEY in the environment.")
            raise SystemExit(2)
        from harness.execution.factory import ExecutorFactory
        executor_factory = ExecutorFactory.create
        inspector = None
        mode = "live (env-dependent)"
    else:
        executor_factory = MockE2BExecutor
        inspector = MockInspector()
        mode = "safe mock (no live E2B)"

    print("=" * 72)
    print("E2B Manual QA Harness — canonical example")
    print(f"Mode: {mode}")
    print("=" * 72)

    orch = E2BOrchestrator(
        executor_factory=executor_factory,
        inspector=inspector,
        progress_callback=lambda e: print(f"  [{e['status']}] {e['stage']}: {e['detail']}"),
    )
    report = orch.run(E2BOrchestrationOptions(
        run_id=args.run_id,
        target_url=args.target,
        plan=plan,
        artifacts_dir=Path(args.artifacts_dir),
        enable_vision=not args.live,      # mock inspector in demo; wire real vision for live as needed
        enable_bug_review=not args.live,
        vision_rounds=1,
    ))
    print(json.dumps({
        "run_id": report.run_id,
        "status": report.status,
        "mode": mode,
        "report_path": report.artifacts.get("orchestration_report"),
        "errors": report.errors,
    }, indent=2))
    if report.status != "COMPLETED" and not args.live:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
