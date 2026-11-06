"""Tests for STORY-E2B-006.3 — Seeded-Bug Benchmark."""
from __future__ import annotations

import json
from pathlib import Path

from evals.e2b_seeded_benchmark import E2BSeededBugBenchmark, default_mock_detector


def test_seeded_benchmark_computes_metrics(tmp_path):
    fixtures = tmp_path / "bugs.json"
    fixtures.write_text(json.dumps([
        {"id": "p1", "name": "seeded layout", "category": "layout", "seeded": True, "expected": True, "signal": {"category": "layout", "issue": "overflow"}},
        {"id": "p2", "name": "seeded contrast", "category": "contrast", "seeded": True, "expected": True, "signal": {"category": "contrast", "issue": "low contrast"}},
        {"id": "n1", "name": "clean", "category": "none", "seeded": False, "expected": False},
    ]))
    bench = E2BSeededBugBenchmark(fixtures, repeats=3)  # default mock detector detects positives, no FP
    report = bench.run()
    s = report["summary"]
    assert s["total_cases"] == 3
    assert s["seeded_bug_cases"] == 2
    assert s["negative_cases"] == 1
    assert s["tp"] == 2 and s["fn"] == 0 and s["fp"] == 0 and s["tn"] == 1
    assert s["detection_rate"] == 1.0
    assert s["false_positive_rate"] == 0.0
    assert s["reproducibility_rate"] == 1.0


def test_seeded_benchmark_handles_misses_and_fp(tmp_path):
    fixtures = tmp_path / "bugs.json"
    fixtures.write_text(json.dumps([
        {"id": "p1", "name": "seeded", "category": "layout", "seeded": True, "expected": True},
        {"id": "n1", "name": "clean", "category": "none", "seeded": False, "expected": False},
    ]))

    def detector(case, idx):
        if case["id"] == "p1":
            return {"detected": False, "findings": [{"issue": "none", "severity": "info"}]}
        return {"detected": True, "findings": [{"category": "layout", "issue": "false positive", "severity": "low", "confidence": 0.6}]}

    report = E2BSeededBugBenchmark(fixtures, detector=detector, repeats=2).run()
    s = report["summary"]
    assert s["fn"] == 1 and s["fp"] == 1 and s["tp"] == 0 and s["tn"] == 0
    assert s["detection_rate"] == 0.0
    assert s["false_positive_rate"] == 1.0
    assert report["cases"][0]["outcome"] == "FN"
    assert report["cases"][1]["outcome"] == "FP"


def test_seeded_benchmark_reproducibility_with_flake(tmp_path):
    fixtures = tmp_path / "bugs.json"
    fixtures.write_text(json.dumps([{"id": "p1", "category": "layout", "seeded": True, "expected": True}]))
    calls = {"i": 0}

    def flaky(case, idx):
        calls["i"] += 1
        # alternate detected/missed across repeats
        detected = idx % 2 == 0
        return {"detected": detected, "findings": ([{"category": "layout", "issue": "x", "severity": "medium", "confidence": 0.9}] if detected else [{"issue": "none", "severity": "info"}])}

    report = E2BSeededBugBenchmark(fixtures, detector=flaky, repeats=4).run()
    assert calls["i"] == 4
    case = report["cases"][0]
    assert case["detections"] == 2
    assert case["detection_rate"] == 0.5
    assert case["reproducible"] is False
    assert report["summary"]["reproducibility_rate"] == 0.0


def test_seeded_benchmark_saves_report(tmp_path):
    fixtures = tmp_path / "bugs.json"
    fixtures.write_text(json.dumps([{"id": "p1", "category": "layout", "seeded": True, "expected": True}]))
    out = tmp_path / "reports" / "e2b-benchmark.json"
    report = E2BSeededBugBenchmark(fixtures, repeats=1).run_and_save(out)
    assert out.exists()
    saved = json.loads(out.read_text())
    assert saved["benchmark"] == "e2b-seeded-bug-benchmark"
    assert "detection_rate" in saved["summary"]
    assert "false_positive_rate" in saved["summary"]
    assert "reproducibility_rate" in saved["summary"]
    assert report["report_path"] == str(out)
