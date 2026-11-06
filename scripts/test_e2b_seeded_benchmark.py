#!/usr/bin/env python3
"""Demo for STORY-E2B-006.3: Seeded-Bug Benchmark.

Runs seeded-bug cases through an injectable/mock detector (E2B+vision adapted
path), computes detection rate, FP rate, and reproducibility, and writes the
report to evals/reports/e2b-benchmark.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.e2b_seeded_benchmark import E2BSeededBugBenchmark, default_mock_detector


def demo_detector(case, run_index):
    # Simulate a strong E2B+vision detector with slight reproducibility noise on one case.
    if case["id"] == "e2b-b1" and run_index == 2:
        return {"detected": False, "findings": [{"category": "layout", "issue": "none", "severity": "info", "confidence": 0.7}]}
    return default_mock_detector(case, run_index)


def main() -> None:
    print("=" * 72)
    print("STORY-E2B-006.3: Seeded-Bug Benchmark")
    print("=" * 72)
    bench = E2BSeededBugBenchmark("evals/fixtures/e2b_seeded_bugs.json", detector=demo_detector, repeats=3)
    report = bench.run_and_save("evals/reports/e2b-benchmark.json")
    s = report["summary"]
    print(json.dumps(s, indent=2))
    print("\nCase outcomes:")
    for c in report["cases"]:
        print(f"  - {c['case_id']} [{c['category']} seeded={c['seeded_bug']}]: outcome={c['outcome']} detections={c['detections']}/{len(c['runs'])} reproducible={c['reproducible']}")
    print(f"\nReport: evals/reports/e2b-benchmark.json")

    assert s["total_cases"] == 4
    assert s["seeded_bug_cases"] == 3
    assert s["negative_cases"] == 1
    assert "detection_rate" in s and "false_positive_rate" in s and "reproducibility_rate" in s
    assert Path("evals/reports/e2b-benchmark.json").exists()
    saved = json.loads(Path("evals/reports/e2b-benchmark.json").read_text())
    assert saved["benchmark"] == "e2b-seeded-bug-benchmark"
    print("\n✓ 006.3 demo passed: seeded-bug benchmark computed detection/FP/reproducibility and generated report.")
    print("=" * 72)


if __name__ == "__main__":
    main()
