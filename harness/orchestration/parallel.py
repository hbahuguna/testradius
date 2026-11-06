"""Parallel orchestration for executor runs (STORY-E2B-006.1).

Runs multiple sandbox/executor jobs concurrently with configurable concurrency,
aggregates results, and isolates per-run failures.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..execution.base import ExecutionResult, ExecutionStatus, ExecutorConfig
from ..execution.factory import ExecutorFactory


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ParallelRunSpec:
    """Specification for one parallel run."""

    run_id: str
    target_url: str
    plan: Dict[str, Any]
    executor_type: str = "e2b"
    artifacts_dir: str = "artifacts"
    timeout_seconds: int = 600
    headless: bool = True
    record_video: bool = True
    capture_screenshots: bool = True
    capture_traces: bool = True
    model: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    label: Optional[str] = None


@dataclass
class ParallelRunRecord:
    spec: ParallelRunSpec
    status: str
    started_at: str
    ended_at: str
    duration_ms: int
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    sandbox_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["spec"] = asdict(self.spec)
        return d


@dataclass
class ParallelAggregateResult:
    orchestration_id: str
    started_at: str
    ended_at: str
    duration_ms: int
    concurrency: int
    total: int
    completed: int
    failed: int
    stopped: int
    timeout: int
    runs: List[ParallelRunRecord] = field(default_factory=list)
    failures: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.failed == 0 and self.timeout == 0 and self.completed == self.total

    def to_dict(self) -> Dict[str, Any]:
        return {
            "orchestration_id": self.orchestration_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "concurrency": self.concurrency,
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "stopped": self.stopped,
            "timeout": self.timeout,
            "success": self.success,
            "runs": [r.to_dict() for r in self.runs],
            "failures": self.failures,
        }

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path


ExecutorRunner = Callable[[ParallelRunSpec], ExecutionResult]


class ParallelOrchestrator:
    """Run multiple executor jobs in parallel and aggregate results."""

    def __init__(
        self,
        *,
        executor_runner: Optional[ExecutorRunner] = None,
        default_executor_type: str = "e2b",
    ):
        self.executor_runner = executor_runner
        self.default_executor_type = default_executor_type

    def run(
        self,
        specs: Sequence[ParallelRunSpec],
        *,
        concurrency: int = 2,
        fail_fast: bool = False,
        orchestration_id: Optional[str] = None,
        report_path: Optional[Path] = None,
    ) -> ParallelAggregateResult:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        specs = list(specs)
        orch_id = orchestration_id or f"orch-{int(time.time() * 1000)}"
        started = time.time()
        started_at = _utc_now()
        records: List[ParallelRunRecord] = []
        failures: List[Dict[str, Any]] = []

        max_workers = min(concurrency, max(1, len(specs)))
        future_map = {}
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for spec in specs:
                if not spec.executor_type:
                    spec.executor_type = self.default_executor_type
                future_map[pool.submit(self._run_one, spec)] = spec

            for future in as_completed(future_map):
                spec = future_map[future]
                try:
                    record = future.result()
                except Exception as exc:  # should be rare; _run_one isolates
                    ended_at = _utc_now()
                    record = ParallelRunRecord(
                        spec=spec,
                        status=ExecutionStatus.FAILED.value,
                        started_at=started_at,
                        ended_at=ended_at,
                        duration_ms=0,
                        error=f"orchestrator_error: {exc}",
                    )
                records.append(record)
                if record.status in {ExecutionStatus.FAILED.value, ExecutionStatus.TIMEOUT.value}:
                    failures.append(
                        {
                            "run_id": spec.run_id,
                            "label": spec.label,
                            "executor_type": spec.executor_type,
                            "status": record.status,
                            "error": record.error,
                        }
                    )
                    if fail_fast:
                        for f in future_map:
                            f.cancel()
                        break

        # Preserve input order in final report for readability
        order = {s.run_id: i for i, s in enumerate(specs)}
        records.sort(key=lambda r: order.get(r.spec.run_id, 10**9))
        ended_at = _utc_now()
        duration_ms = int((time.time() - started) * 1000)
        completed = sum(1 for r in records if r.status == ExecutionStatus.COMPLETED.value)
        failed = sum(1 for r in records if r.status == ExecutionStatus.FAILED.value)
        stopped = sum(1 for r in records if r.status == ExecutionStatus.STOPPED.value)
        timeout = sum(1 for r in records if r.status == ExecutionStatus.TIMEOUT.value)

        agg = ParallelAggregateResult(
            orchestration_id=orch_id,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            concurrency=max_workers,
            total=len(specs),
            completed=completed,
            failed=failed,
            stopped=stopped,
            timeout=timeout,
            runs=records,
            failures=failures,
        )
        if report_path:
            agg.save(report_path)
        return agg

    def _run_one(self, spec: ParallelRunSpec) -> ParallelRunRecord:
        t0 = time.time()
        started_at = _utc_now()
        try:
            if self.executor_runner is not None:
                result = self.executor_runner(spec)
            else:
                config = ExecutorConfig(
                    run_id=spec.run_id,
                    target_url=spec.target_url,
                    plan=spec.plan,
                    artifacts_dir=Path(spec.artifacts_dir),
                    timeout_seconds=spec.timeout_seconds,
                    headless=spec.headless,
                    record_video=spec.record_video,
                    capture_screenshots=spec.capture_screenshots,
                    capture_traces=spec.capture_traces,
                    model=spec.model,
                    metadata={**dict(spec.metadata), "parallel_orchestration": True},
                )
                executor = ExecutorFactory.create_executor(config, executor_type=spec.executor_type)
                try:
                    executor.prepare()
                    result = executor.execute_plan()
                finally:
                    try:
                        executor.cleanup()
                    except Exception:
                        pass
            ended_at = _utc_now()
            duration_ms = int((time.time() - t0) * 1000)
            sandbox_id = None
            if isinstance(result.metadata, dict):
                sandbox_id = result.metadata.get("sandbox_id") or (result.metadata.get("delivery") or {}).get("sandbox_id")
            return ParallelRunRecord(
                spec=spec,
                status=result.status.value if isinstance(result.status, ExecutionStatus) else str(result.status),
                started_at=result.started_at or started_at,
                ended_at=result.ended_at or ended_at,
                duration_ms=result.duration_ms if result.duration_ms is not None else duration_ms,
                result=result.to_dict(),
                error=result.error,
                sandbox_id=sandbox_id,
            )
        except Exception as exc:
            ended_at = _utc_now()
            duration_ms = int((time.time() - t0) * 1000)
            return ParallelRunRecord(
                spec=spec,
                status=ExecutionStatus.FAILED.value,
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=duration_ms,
                error=str(exc),
            )
