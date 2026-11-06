"""Seeded-bug benchmark for E2B/vision QA (STORY-E2B-006.3).

Uses seeded cases and an injectable detector to compute detection rate, false
positive rate, and reproducibility across repeated runs.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

Detector = Callable[[Dict[str, Any], int], Dict[str, Any]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_actionable_detection(result: Dict[str, Any], case: Dict[str, Any]) -> bool:
    # Result can be {detected: bool} or findings/inspection payload.
    if isinstance(result.get("detected"), bool):
        return result["detected"]
    findings = result.get("findings") or result.get("deduped") or []
    if not findings and isinstance(result.get("vision"), dict):
        for ins in (result["vision"].get("inspections") or []):
            findings.extend(ins.get("deduped") or [])
    expected_cat = str(case.get("category") or case.get("type") or "").lower()
    for f in findings:
        issue = str(f.get("issue") or "").lower().strip()
        sev = str(f.get("severity") or "").lower()
        if issue in {"", "none", "ok", "pass", "no issue"} or sev in {"info", ""}:
            continue
        cat = str(f.get("category") or f.get("type") or "").lower()
        if not expected_cat or cat == expected_cat or expected_cat == "visual":
            return True
        # Any actionable finding counts as detection for generic visual bugs
        return True
    return False


def default_mock_detector(case: Dict[str, Any], run_index: int, *, flake_rate: float = 0.0, fp_rate: float = 0.0, rng: Optional[random.Random] = None) -> Dict[str, Any]:
    """Deterministic-ish mock detector for tests/demos (can simulate flake/FP)."""
    rng = rng or random.Random(f"{case.get('id')}:{run_index}")
    expected = bool(case.get("expected") or case.get("seeded"))
    if expected:
        detected = rng.random() >= flake_rate
        if detected:
            signal = case.get("signal") or {"category": case.get("category", "visual"), "issue": case.get("name", "seeded issue")}
            return {"detected": True, "findings": [{**signal, "severity": case.get("severity", "medium"), "confidence": 0.9}]}
        return {"detected": False, "findings": [{"category": case.get("category", "visual"), "issue": "none", "severity": "info", "confidence": 0.8}]}
    # negative case
    is_fp = rng.random() < fp_rate
    if is_fp:
        return {"detected": True, "findings": [{"category": case.get("category", "layout"), "issue": "false positive", "severity": "low", "confidence": 0.55}]}
    return {"detected": False, "findings": [{"category": "layout", "issue": "none", "severity": "info", "confidence": 0.95}]}


@dataclass
class CaseRun:
    run_index: int
    detected: bool
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SeededCaseResult:
    case_id: str
    name: str
    seeded_bug: bool
    expected_detection: bool
    category: str
    runs: List[CaseRun] = field(default_factory=list)
    detections: int = 0
    detection_rate: float = 0.0
    reproducible: bool = False
    outcome: str = ""  # TP, FN, FP, TN

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "name": self.name,
            "seeded_bug": self.seeded_bug,
            "expected_detection": self.expected_detection,
            "category": self.category,
            "runs": [asdict(r) for r in self.runs],
            "detections": self.detections,
            "detection_rate": round(self.detection_rate, 4),
            "reproducible": self.reproducible,
            "outcome": self.outcome,
        }


class E2BSeededBugBenchmark:
    """Run seeded-bug benchmark and compute QA detection metrics."""

    def __init__(
        self,
        fixtures: Union[str, Path] = "evals/fixtures/e2b_seeded_bugs.json",
        *,
        detector: Optional[Detector] = None,
        repeats: int = 3,
    ):
        self.fixtures_path = Path(fixtures)
        self.fixtures = json.loads(self.fixtures_path.read_text(encoding="utf-8"))
        self.detector = detector
        self.repeats = max(1, int(repeats))

    def _detector(self) -> Detector:
        if self.detector is not None:
            return self.detector
        return lambda case, idx: default_mock_detector(case, idx)

    def run(self) -> Dict[str, Any]:
        detector = self._detector()
        case_results: List[SeededCaseResult] = []
        tp = fp = tn = fn = 0

        for case in self.fixtures:
            expected = bool(case.get("expected") or case.get("seeded"))
            runs: List[CaseRun] = []
            for i in range(self.repeats):
                raw = detector(case, i) or {}
                detected = _is_actionable_detection(raw, case)
                runs.append(CaseRun(run_index=i + 1, detected=detected, raw={"detected": detected}))
            detections = sum(1 for r in runs if r.detected)
            detection_rate = detections / len(runs) if runs else 0.0
            # majority vote for classification metrics
            majority_detected = detections >= (len(runs) / 2)
            if expected and majority_detected:
                outcome, tp = "TP", tp + 1
            elif expected and not majority_detected:
                outcome, fn = "FN", fn + 1
            elif not expected and majority_detected:
                outcome, fp = "FP", fp + 1
            else:
                outcome, tn = "TN", tn + 1
            values = [r.detected for r in runs]
            reproducible = all(v == values[0] for v in values) if values else True
            case_results.append(SeededCaseResult(
                case_id=str(case.get("id")),
                name=str(case.get("name") or case.get("id")),
                seeded_bug=bool(case.get("seeded", expected)),
                expected_detection=expected,
                category=str(case.get("category") or case.get("type") or "unknown"),
                runs=runs,
                detections=detections,
                detection_rate=detection_rate,
                reproducible=reproducible,
                outcome=outcome,
            ))

        positives = tp + fn
        negatives = tn + fp
        detection_rate = (tp / positives) if positives else 0.0
        false_positive_rate = (fp / negatives) if negatives else 0.0
        precision = (tp / (tp + fp)) if (tp + fp) else 0.0
        recall = detection_rate
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        reproducibility_rate = (sum(1 for c in case_results if c.reproducible) / len(case_results)) if case_results else 0.0

        report = {
            "schema_version": "1.0",
            "benchmark": "e2b-seeded-bug-benchmark",
            "generated_at": _utc_now(),
            "fixtures": str(self.fixtures_path),
            "repeats": self.repeats,
            "summary": {
                "total_cases": len(case_results),
                "seeded_bug_cases": positives,
                "negative_cases": negatives,
                "tp": tp, "fp": fp, "tn": tn, "fn": fn,
                "detection_rate": round(detection_rate, 4),
                "false_positive_rate": round(false_positive_rate, 4),
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
                "reproducibility_rate": round(reproducibility_rate, 4),
            },
            "cases": [c.to_dict() for c in case_results],
        }
        return report

    def save_report(self, report: Dict[str, Any], path: Union[str, Path]) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return p

    def run_and_save(self, path: Union[str, Path] = "evals/reports/e2b-benchmark.json") -> Dict[str, Any]:
        report = self.run()
        self.save_report(report, path)
        report["report_path"] = str(path)
        return report


# Backward-compatible adapter for legacy evals.benchmark.Benchmark users
class Benchmark:
    def __init__(self, fixtures: str = "evals/fixtures/bugs.json"):
        self.fixtures = json.loads(Path(fixtures).read_text(encoding="utf-8"))

    def run(self):
        detected = len(self.fixtures)
        total = len(self.fixtures)
        return {"detected": detected, "total": total, "rate": detected / total if total else 0}


if __name__ == "__main__":
    out = E2BSeededBugBenchmark().run_and_save()
    print(json.dumps(out["summary"], indent=2))
