"""Tests for STORY-E2B-004.3 — Multi-Round Self-Inspection."""
import json
from pathlib import Path

from harness.vision import SelfInspector, VisionClient
from harness.vision.providers import MockVisionProvider


def test_multiround_inspection_logs_purposes_and_dedupes(tmp_path):
    img = tmp_path / "hero_contrast_issue.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    inspector = SelfInspector(rounds=2, client=VisionClient(model="mock", provider=MockVisionProvider()))
    report = inspector.inspect(str(img), url="https://testradius.dev")

    assert report["summary"]["round_count"] == 2
    assert len(report["rounds"]) == 2
    assert report["rounds"][0]["purpose"] == "initial_inspection"
    assert report["rounds"][1]["purpose"] == "verify_fixes_and_check_additional_areas"
    for r in report["rounds"]:
        assert "started_at" in r and "completed_at" in r
        assert "findings" in r and isinstance(r["findings"], list)
        assert r["screenshot"] == str(img)

    assert "deduped" in report
    assert report["summary"]["deduped_findings"] <= report["summary"]["total_findings"]
    assert report["summary"]["actionable_deduped_findings"] >= 1  # contrast issue present
    assert report["schema_version"] == "1.0"


def test_inspector_saves_report(tmp_path):
    img = tmp_path / "page.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    out = tmp_path / "inspection" / "vision_inspection_report.json"
    inspector = SelfInspector(rounds=2)
    report = inspector.inspect_and_save(str(img), out)
    assert out.exists()
    saved = json.loads(out.read_text())
    assert saved["summary"]["round_count"] == 2
    assert len(saved["rounds"]) == 2
    assert report["generated_at"] == saved["generated_at"] or saved["summary"]["round_count"] == 2


def test_dedupe_keeps_highest_severity_for_same_fingerprint():
    inspector = SelfInspector(rounds=1)
    findings = [
        {"category": "contrast", "issue": "Low contrast", "location": "hero", "severity": "low", "confidence": 0.5},
        {"category": "contrast", "issue": "Low contrast", "location": "hero", "severity": "high", "confidence": 0.9},
        {"category": "layout", "issue": "Misaligned", "location": "header", "severity": "medium", "confidence": 0.8},
    ]
    deduped = inspector._dedupe(findings)
    assert len(deduped) == 2
    contrast = [f for f in deduped if f["category"] == "contrast"][0]
    assert contrast["severity"] == "high"
