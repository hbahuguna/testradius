"""Tests for STORY-E2B-006.1 — Parallel Sandbox Runs."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from harness.execution.base import ExecutionResult, ExecutionStatus
from harness.orchestration.parallel import ParallelOrchestrator, ParallelRunSpec


def _result(spec: ParallelRunSpec, status=ExecutionStatus.COMPLETED, error=None, sandbox_id=None) -> ExecutionResult:
    return ExecutionResult(
        run_id=spec.run_id,
        status=status,
        started_at="2026-01-01T00:00:00Z",
        ended_at="2026-01-01T00:00:01Z",
        duration_ms=1000,
        error=error,
        metadata={"sandbox_id": sandbox_id} if sandbox_id else {},
        summary={"total_steps": 1, "passed_steps": 1 if status == ExecutionStatus.COMPLETED else 0, "failed_steps": 0 if status == ExecutionStatus.COMPLETED else 1},
    )


def test_parallel_runs_aggregate_and_respect_concurrency():
    lock = threading.Lock()
    active = {"n": 0, "max": 0}

    def runner(spec: ParallelRunSpec) -> ExecutionResult:
        with lock:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        time.sleep(0.05)
        with lock:
            active["n"] -= 1
        return _result(spec, sandbox_id=f"sbx-{spec.run_id}")

    specs = [ParallelRunSpec(run_id=f"r{i}", target_url="https://example.com", plan={"plan_id": f"p{i}", "steps": []}) for i in range(5)]
    orch = ParallelOrchestrator(executor_runner=runner)
    agg = orch.run(specs, concurrency=2, orchestration_id="orch-test")

    assert agg.total == 5
    assert agg.completed == 5
    assert agg.failed == 0
    assert agg.concurrency == 2
    assert agg.success is True
    assert active["max"] <= 2
    assert len(agg.runs) == 5
    assert [r.spec.run_id for r in agg.runs] == [f"r{i}" for i in range(5)]  # input order preserved
    assert all(r.sandbox_id == f"sbx-{r.spec.run_id}" for r in agg.runs)


def test_parallel_handles_failures_without_stopping_other_runs():
    def runner(spec: ParallelRunSpec) -> ExecutionResult:
        if spec.run_id == "r2":
            return _result(spec, status=ExecutionStatus.FAILED, error="boom")
        if spec.run_id == "r3":
            raise RuntimeError("executor crash")
        return _result(spec)

    specs = [ParallelRunSpec(run_id=f"r{i}", target_url="https://x", plan={"steps": []}) for i in range(5)]
    agg = ParallelOrchestrator(executor_runner=runner).run(specs, concurrency=3)

    assert agg.total == 5
    assert agg.completed == 3
    assert agg.failed == 2
    assert agg.success is False
    statuses = {r.spec.run_id: r.status for r in agg.runs}
    assert statuses["r2"] == "FAILED"
    assert statuses["r3"] == "FAILED"
    assert len(agg.failures) == 2
    assert any(f["run_id"] == "r3" and "executor crash" in (f.get("error") or "") for f in agg.failures)


def test_parallel_fail_fast_cancels_pending():
    started = []

    def runner(spec: ParallelRunSpec) -> ExecutionResult:
        started.append(spec.run_id)
        if spec.run_id == "r0":
            time.sleep(0.02)
            return _result(spec, status=ExecutionStatus.FAILED, error="fail fast")
        time.sleep(0.05)
        return _result(spec)

    specs = [ParallelRunSpec(run_id=f"r{i}", target_url="https://x", plan={"steps": []}) for i in range(6)]
    agg = ParallelOrchestrator(executor_runner=runner).run(specs, concurrency=1, fail_fast=True)
    assert agg.failed >= 1
    assert agg.total == 6
    # with concurrency=1, at least first failed run is recorded; some pending futures cancelled
    assert len(agg.runs) >= 1


def test_parallel_saves_aggregate_report(tmp_path):
    def runner(spec: ParallelRunSpec) -> ExecutionResult:
        return _result(spec)

    specs = [ParallelRunSpec(run_id="r1", target_url="https://x", plan={"steps": []})]
    report = tmp_path / "parallel.json"
    agg = ParallelOrchestrator(executor_runner=runner).run(specs, concurrency=1, report_path=report)
    assert report.exists()
    import json
    data = json.loads(report.read_text())
    assert data["orchestration_id"] == agg.orchestration_id
    assert data["total"] == 1
    assert data["runs"][0]["spec"]["run_id"] == "r1"


def test_parallel_accepts_e2b_executor_type_metadata():
    # validates spec shape for E2B-oriented orchestration (runner injection avoids live E2B)
    def runner(spec: ParallelRunSpec) -> ExecutionResult:
        assert spec.executor_type == "e2b"
        assert spec.metadata.get("template") == "playwright-chromium"
        return _result(spec, sandbox_id="sbx-e2b")

    spec = ParallelRunSpec(
        run_id="e2b-r1", target_url="https://testradius.dev", plan={"plan_id": "P", "steps": [{"step_id": "S1"}]},
        executor_type="e2b", metadata={"template": "playwright-chromium", "allowed_domains": ["testradius.dev"]},
    )
    agg = ParallelOrchestrator(executor_runner=runner).run([spec], concurrency=1)
    assert agg.completed == 1
    assert agg.runs[0].sandbox_id == "sbx-e2b"
