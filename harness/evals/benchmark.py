"""Benchmark runs and eval reports."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .analysis import FailureAnalysis


@dataclass
class BenchmarkRun:
    run_id: str
    target: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    duration_ms: int = 0
    flakes: int = 0


@dataclass
class EvalReport:
    report_id: str
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    benchmarks: List[BenchmarkRun] = field(default_factory=list)
    failure_analysis: Dict[str, Any] = field(default_factory=dict)
    pass_rate: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_benchmark(self, b: BenchmarkRun):
        self.benchmarks.append(b)
        total = sum(x.total for x in self.benchmarks)
        passed = sum(x.passed for x in self.benchmarks)
        self.pass_rate = (passed / total * 100) if total > 0 else 0.0
        return self

    def attach_failures(self, analysis: FailureAnalysis):
        self.failure_analysis = analysis.summary()
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "benchmarks": [asdict(b) for b in self.benchmarks],
            "failure_analysis": self.failure_analysis,
            "pass_rate": round(self.pass_rate, 2),
            "metadata": self.metadata,
        }

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path
