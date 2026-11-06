"""Tests for STORY-E2B-005.2 — Bug Generation from E2B Findings."""
import json
from pathlib import Path

from harness.bugs import BugFiler, BugReportGenerator


def test_legacy_bug_filer_compat():
    filer = BugFiler()
    ticket = filer.generate([{"type": "layout", "issue": "overlap"}], "artifacts/run-1")
    assert "title" in ticket
    assert ticket["evidence"] == "artifacts/run-1"  # legacy raw arg
    assert ticket["severity"] in {"low", "medium", "high", "critical", "info"}
    assert isinstance(ticket["steps"], list)
    try:
        filer.file([{"type": "layout", "issue": "overlap"}], "artifacts/run-1", approved=False)
        assert False, "should require approval"
    except PermissionError:
        pass
    res = filer.file([{"type": "layout", "issue": "overlap"}], "artifacts/run-1", approved=True)
    assert res["status"] == "filed"
    assert "url" in res


def test_generate_repro_ready_report_from_vision_findings(tmp_path):
    run_dir = tmp_path / "run-bug"
    run_dir.mkdir()
    (run_dir / "STEP-01.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (run_dir / "manifest.json").write_text(json.dumps({
        "run_id": "run-bug",
        "artifacts": [
            {"type": "screenshot", "path": "artifacts/run-bug/STEP-01.png", "filename": "STEP-01.png"},
            {"type": "console", "path": "artifacts/run-bug/console.log", "filename": "console.log"},
            {"type": "trace", "path": "artifacts/run-bug/trace.zip", "filename": "trace.zip"},
        ],
    }))
    (run_dir / "console.log").write_text("console error")
    (run_dir / "step_results.json").write_text(json.dumps({
        "steps": [
            {"step_id": "S1", "intent": "Navigate to homepage", "status": "PASSED"},
            {"step_id": "S2", "intent": "Open pricing page", "status": "FAILED"},
        ]
    }))

    findings = [
        {"category": "contrast", "issue": "Low contrast CTA text", "severity": "high", "confidence": 0.91,
         "description": "Primary CTA text has insufficient contrast against button background.", "location": "hero CTA",
         "suggestion": "Use a darker text token or lighter button color to meet WCAG AA."},
        {"category": "layout", "issue": "none", "severity": "info", "confidence": 0.9},
    ]
    gen = BugReportGenerator()
    report = gen.generate(findings=findings, run_dir=run_dir, url="https://testradius.dev/pricing",
                          environment={"browser": "chromium", "viewport": "1280x800"})

    assert "contrast" in report.title.lower() or "Low contrast" in report.title
    assert report.severity == "high"
    assert report.priority == "P1"
    assert len(report.steps_to_reproduce) >= 2
    assert any("Navigate to https://testradius.dev/pricing" in s for s in report.steps_to_reproduce)
    assert report.evidence.manifest_path and Path(report.evidence.manifest_path).exists()
    assert any("STEP-01.png" in s for s in report.evidence.screenshots)
    assert report.evidence.step_results_path
    md = report.render_markdown()
    assert "## Steps to Reproduce" in md
    assert "## Findings" in md
    assert "STEP-01.png" in md or "screenshot" in md.lower()
    d = report.to_dict()
    assert d["priority"] == "P1"
    assert d["fingerprint"]


def test_dedup_by_title_and_fingerprint():
    filer = BugFiler(existing=[{"title": "[Layout] Button overlap in hero (testradius.dev)", "fingerprint": "fp1"}])
    from harness.bugs.generator import BugReport, BugEvidence
    report = BugReport(title="[Layout] Button overlap in hero (testradius.dev)", summary="x", severity="medium", priority="P2", fingerprint="fp1", evidence=BugEvidence())
    assert filer.dedup_report(report) is True
    report2 = BugReport(title="Different", summary="x", severity="medium", priority="P2", fingerprint="fp1", evidence=BugEvidence())
    assert filer.dedup_report(report2) is True
    report3 = BugReport(title="Different", summary="x", severity="medium", priority="P2", fingerprint="fp2", evidence=BugEvidence())
    assert filer.dedup_report(report3) is False
