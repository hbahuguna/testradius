#!/usr/bin/env python3
"""Demo for STORY-E2B-006.1: Parallel Sandbox Runs.

Shows configurable concurrency, aggregated results, and isolated failure handling
for E2B-oriented executor runs. Uses injected mock runners for safe/local CI demo;
live E2B can be enabled by passing real specs through ParallelOrchestrator without
executor_runner injection and configured E2B env.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.execution.base import ExecutionResult, ExecutionStatus
from harness.orchestration.parallel import ParallelOrchestrator, ParallelRunSpec


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()

    lock = threading.Lock()
    active = {"n": 0, "max": 0}

    def mock_e2b_runner(spec: ParallelRunSpec) -> ExecutionResult:
        with lock:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        time.sleep(0.12)  # simulate sandbox execution overlap
        with lock:
            active["n"] -= 1

        if spec.run_id.endswith("-fail"):
            return ExecutionResult(
                run_id=spec.run_id, status=ExecutionStatus.FAILED,
                started_at="t0", ended_at="t1", error="simulated E2B step failure",
                metadata={"executor": "e2b", "sandbox_id": f"sbx-{spec.run_id}"},
                summary={"total_steps": 2, "passed_steps": 1, "failed_steps": 1},
            )
        return ExecutionResult(
            run_id=spec.run_id, status=ExecutionStatus.COMPLETED,
            started_at="t0", ended_at="t1", duration_ms=120,
            metadata={"executor": "e2b", "sandbox_id": f"sbx-{spec.run_id}", "delivery": {"sandbox_id": f"sbx-{spec.run_id}"}},
            summary={"total_steps": 2, "passed_steps": 2, "failed_steps": 0},
            screenshots=[Path(f"artifacts/{spec.run_id}/step.png")],
        )

    specs = []
    for i in range(args.runs):
        rid = f"e2b-parallel-{i}" + ("-fail" if i == 2 else "")
        specs.append(
            ParallelRunSpec(
                run_id=rid,
                target_url="https://testradius.dev",
                plan={"plan_id": f"PLAN-{i}", "steps": [{"step_id": "S1", "intent": "Open homepage"}, {"step_id": "S2", "intent": "Check CTA"}]},
                executor_type="e2b",
                metadata={"template": "playwright-chromium", "parallel_demo": True},
                label=f"case-{i}",
            )
        )

    print("=" * 72)
    print("STORY-E2B-006.1: Parallel Sandbox Runs")
    print("=" * 72)
    orch = ParallelOrchestrator(executor_runner=mock_e2b_runner, default_executor_type="e2b")
    report_path = Path("artifacts/demo_parallel_e2b.json")
    agg = orch.run(specs, concurrency=args.concurrency, orchestration_id="demo-e2b-parallel", report_path=report_path)

    print(json.dumps({
        "orchestration_id": agg.orchestration_id,
        "concurrency_configured": args.concurrency,
        "concurrency_effective": agg.concurrency,
        "total": agg.total,
        "completed": agg.completed,
        "failed": agg.failed,
        "success": agg.success,
        "max_concurrent_observed": active["max"],
        "duration_ms": agg.duration_ms,
        "report_path": str(report_path),
    }, indent=2))

    print("\nPer-run results:")
    for r in agg.runs:
        print(f"  - {r.spec.run_id}: status={r.status} sandbox={r.sandbox_id} error={r.error}")

    assert agg.total == args.runs
    assert agg.concurrency == min(args.concurrency, args.runs)
    assert active["max"] <= agg.concurrency
    assert agg.completed == args.runs - 1
    assert agg.failed == 1
    assert len(agg.failures) == 1
    assert report_path.exists()
    saved = json.loads(report_path.read_text())
    assert saved["total"] == args.runs

    print("\n✓ 006.1 demo passed: multiple E2B-oriented runs executed in parallel, concurrency respected, results aggregated, failure isolated.")
    print("=" * 72)


if __name__ == "__main__":
    main()
