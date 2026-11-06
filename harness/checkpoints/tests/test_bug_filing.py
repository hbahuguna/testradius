"""Tests for STORY-E2B-005.1/005.3 — checkpoint-gated filing and connectors."""
import json
from pathlib import Path

import pytest

from harness.checkpoints import ApprovalRegistry, BugFilingWorkflow
from harness.connectors import GitHubConnector


def _seed_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run-005"
    run_dir.mkdir()
    (run_dir / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (run_dir / "manifest.json").write_text(json.dumps({
        "run_id": "run-005",
        "artifacts": [{"type": "screenshot", "path": "artifacts/run-005/shot.png", "filename": "shot.png"}],
    }))
    (run_dir / "vision_inspection_report.json").write_text(json.dumps({
        "deduped": [{"category": "overlap", "issue": "CTA overlaps hero text", "severity": "high", "confidence": 0.9,
                     "description": "CTA overlaps hero heading", "location": "hero", "suggestion": "Fix z-index/spacing"}]
    }))
    return run_dir


def test_prepare_review_shows_findings_screenshots_and_blocks_filing(tmp_path):
    run_dir = _seed_run(tmp_path)
    registry = ApprovalRegistry()
    wf = BugFilingWorkflow(registry=registry, connector=GitHubConnector(repo="org/repo", dry_run=True))
    pkg = wf.prepare_review(approval_id="ap-1", run_dir=run_dir, url="https://testradius.dev")

    assert pkg["approved"] is False
    assert pkg["report"]["title"]
    assert "screenshot" in pkg["review_text"].lower()
    assert "shot.png" in pkg["review_text"]
    assert "BLOCKED until an authorized reviewer approves" in pkg["review_text"]
    assert (run_dir / "bug_review_package.json").exists()
    assert (run_dir / "bug_report.md").exists()
    assert (run_dir / "bug_filing_audit.json").exists()

    # Filing blocked
    with pytest.raises(PermissionError):
        wf.file_after_approval(approval_id="ap-1", run_dir=run_dir, url="https://testradius.dev")


def test_approve_then_file_dry_run_with_audit(tmp_path):
    run_dir = _seed_run(tmp_path)
    registry = ApprovalRegistry()
    connector = GitHubConnector(repo="org/repo", dry_run=True)
    wf = BugFilingWorkflow(registry=registry, connector=connector)
    wf.prepare_review(approval_id="ap-2", run_dir=run_dir, url="https://testradius.dev")
    wf.approve("ap-2", actor="qa-lead", detail="Reviewed findings and screenshots")
    result = wf.file_after_approval(approval_id="ap-2", actor="qa-lead", run_dir=run_dir, url="https://testradius.dev")

    assert result["approved"] is True
    assert result["status"] == "dry_run"
    assert "github.com/org/repo" in result["url"]
    assert result["report"]["evidence"]["screenshots"]

    state = registry.get("ap-2")
    actions = [e.action for e in state.audit_log]
    assert "REVIEW_PREPARED" in actions
    assert "APPROVE" in actions
    assert any(a.startswith("FILE_") for a in actions)


def test_connector_dedup_blocks_duplicate(tmp_path):
    run_dir = _seed_run(tmp_path)
    registry = ApprovalRegistry()
    # Existing issue with matching title-ish characteristics via exact title injection
    wf = BugFilingWorkflow(registry=registry, connector=GitHubConnector(repo="org/repo", dry_run=True))
    pkg = wf.prepare_review(approval_id="ap-3", run_dir=run_dir, url="https://testradius.dev")
    wf.approve("ap-3", actor="qa-lead")
    title = pkg["report"]["title"]
    result = wf.file_after_approval(
        approval_id="ap-3", actor="qa-lead", run_dir=run_dir, url="https://testradius.dev",
        existing_issues=[{"title": title, "url": "https://github.com/org/repo/issues/99"}],
    )
    assert result["status"] == "duplicate"
    state = registry.get("ap-3")
    assert "FILE_DUPLICATE" in [e.action for e in state.audit_log]


def test_github_connector_dry_run_links_evidence():
    from harness.bugs.generator import BugReport, BugEvidence
    report = BugReport(
        title="[Overlap] CTA overlaps hero", summary="x", severity="high", priority="P1",
        steps_to_reproduce=["Navigate"], evidence=BugEvidence(screenshots=["artifacts/run/s.png"], manifest_path="artifacts/run/manifest.json"),
        findings=[{"category": "overlap", "issue": "CTA overlaps hero", "severity": "high"}], fingerprint="fp",
    )
    res = GitHubConnector(repo="org/repo", dry_run=True).file(report)
    assert res["status"] == "dry_run"
    assert "s.png" in res["body"]
    assert "manifest.json" in res["body"]
    assert res["evidence"]["screenshots"] == ["artifacts/run/s.png"]
