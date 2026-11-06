"""Computer-use evals: golden plans + seeded variants with flake tracking (008.7.3)."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

from harness.computer_use.gemini_client import MockGeminiComputerUseClient
from harness.computer_use.metrics import aggregate_metrics, compute_run_metrics
from harness.computer_use.primitives import MockComputerUsePrimitives
from harness.computer_use.runner import ComputerUseRunner


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ComputerUseEval:
    """Repeat each eval case with mocks to measure pass rate + flake."""

    def __init__(self, fixtures: str | Path = "evals/fixtures/computer_use_eval_cases.json", repeats: int = 3):
        self.fixtures = json.loads(Path(fixtures).read_text())
        self.repeats = max(1, int(repeats))

    def _client_for(self, case: Dict[str, Any]) -> MockGeminiComputerUseClient:
        if case.get("mock_script") == "out_of_domain":
            return MockGeminiComputerUseClient(script=[{"action_type": "navigate", "url": "https://evil.example.com/", "reason": "bad"}] * 6)
        if case.get("expected") == "fail_product":
            return MockGeminiComputerUseClient(
                script=[{"action_type": "navigate", "url": "https://testradius.dev/", "reason": "x"}] * 6,
                assess_pass=False,
            )
        return MockGeminiComputerUseClient(script=[
            {"action_type": "navigate", "url": "https://testradius.dev/", "reason": "x"},
            {"action_type": "assert", "reason": "x"},
            {"action_type": "click", "x": 100, "y": 100, "reason": "x"},
        ])

    def run(self) -> Dict[str, Any]:
        case_results: List[Dict[str, Any]] = []
        summaries: List[Any] = []
        def _outcome(summary: Any) -> str:
            steps = getattr(summary, "steps", []) or []
            sts = [getattr(s, "status", "") for s in steps]
            if any(s == "infra_error" for s in sts):
                return "infra_error"
            if any(s == "fail_product" for s in sts):
                return "fail_product"
            if any(s == "fail_agent" for s in sts):
                return "fail_agent"
            if any(s == "blocked" for s in sts):
                return "blocked"
            return getattr(summary, "status", "") or "pass"

        for case in self.fixtures:
            plan = json.loads(Path(case["plan"]).read_text())
            statuses: List[str] = []
            for i in range(self.repeats):
                with tempfile.TemporaryDirectory() as tmp:
                    client = self._client_for(case)
                    runner = ComputerUseRunner(primitives=MockComputerUsePrimitives(), gemini_client=client, artifacts_dir=tmp, mode="local_spike")
                    summary = runner.run(run_id=f"{case['id']}-r{i+1}", plan=plan)
                    summaries.append(summary)
                    statuses.append(_outcome(summary))
            # Flake: not all runs share the same outcome.
            flake = len(set(statuses)) > 1
            expected = case.get("expected", "pass")
            def _matches(outcome: str) -> bool:
                if expected == "pass":
                    return outcome in {"COMPLETED", "pass"}
                if expected == "fail_product":
                    return outcome == "fail_product"
                if expected == "blocked":
                    return outcome in {"blocked", "BLOCKED"}
                return outcome == expected
            case_results.append({
                "id": case["id"],
                "name": case.get("name"),
                "expected": expected,
                "seeded_bug": case.get("seeded_bug", False),
                "statuses": statuses,
                "flake": flake,
                "pass_rate": round(sum(1 for s in statuses if _matches(s)) / len(statuses), 4) if statuses else 0.0,
            })
        agg = aggregate_metrics(summaries)
        flake_rate = round(sum(1 for c in case_results if c["flake"]) / max(1, len(case_results)), 4)
        report = {
            "schema_version": "1.0",
            "eval": "computer-use-eval",
            "generated_at": _utc_now(),
            "repeats": self.repeats,
            "cases": case_results,
            "summary": {
                "total_cases": len(case_results),
                "flake_rate": flake_rate,
                "overall_pass_rate": agg.get("overall_pass_rate"),
                "agent_vs_product_failure_rate": agg.get("agent_vs_product_failure_rate"),
                "total_retries": agg.get("total_retries"),
                "avg_runtime_s": agg.get("avg_runtime_s"),
            },
        }
        return report

    def save_report(self, report: Dict[str, Any], path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, indent=2))
        return p


if __name__ == "__main__":
    report = ComputerUseEval().run()
    out = ComputerUseEval().save_report(report, "evals/reports/computer-use-eval.json")
    print(json.dumps(report["summary"], indent=2))
    print(f"Report: {out}")
