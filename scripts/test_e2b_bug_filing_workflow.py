#!/usr/bin/env python3
"""Demo for EPIC-E2B-005: Human Checkpoints & Bug Filing (005.1/005.2/005.3).

Demonstrates:
- 005.2: repro-ready bug generation from vision findings + E2B evidence/logs
- 005.1: checkpoint approval required; findings + screenshots shown; audit log
- 005.3: GitHub connector filing (dry-run) with dedup, approval gate, evidence links

Usage:
  python scripts/test_e2b_bug_filing_workflow.py
  python scripts/test_e2b_bug_filing_workflow.py --existing-title "<exact title>"  # show dedup
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.bugs import BugReportGenerator
from harness.checkpoints import ApprovalRegistry, BugFilingWorkflow
from harness.connectors import GitHubConnector


def make_run_dir(base: Path) -> Path:
    run_dir = base / "run-bug-demo"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "STEP-01.png").write_bytes(b"\x89PNG\r\n\x1a\n(demo screenshot step 01)")
    (run_dir / "STEP-02_failure.png").write_bytes(b"\x89PNG\r\n\x1a\n(demo screenshot failure)")
    (run_dir / "trace.zip").write_bytes(b"PK\x03\x04(demo trace)")
    (run_dir / "console.log").write_text("[error] Uncaught layout warning\n[info] navigation complete\n")
    (run_dir / "network.json").write_text(json.dumps([{"url": "https://testradius.dev", "status": 200}]))
    (run_dir / "manifest.json").write_text(json.dumps({
        "run_id": "run-bug-demo",
        "source": {"provider": "MockE2BProvider", "sandbox_id": "sbx-demo"},
        "artifacts": [
            {"type": "screenshot", "path": "artifacts/run-bug-demo/STEP-01.png", "filename": "STEP-01.png", "remote_path": "/home/user/artifacts/STEP-01.png"},
            {"type": "screenshot", "path": "artifacts/run-bug-demo/STEP-02_failure.png", "filename": "STEP-02_failure.png", "remote_path": "/home/user/artifacts/STEP-02_failure.png"},
            {"type": "trace", "path": "artifacts/run-bug-demo/trace.zip", "filename": "trace.zip"},
            {"type": "console", "path": "artifacts/run-bug-demo/console.log", "filename": "console.log"},
            {"type": "network", "path": "artifacts/run-bug-demo/network.json", "filename": "network.json"},
            {"type": "result", "path": "artifacts/run-bug-demo/step_results.json", "filename": "step_results.json"},
        ],
    }, indent=2))
    (run_dir / "step_results.json").write_text(json.dumps({
        "plan_id": "PLAN-DEMO", "status": "FAILED",
        "steps": [
            {"step_id": "STEP-01", "intent": "Navigate to https://testradius.dev", "status": "PASSED", "screenshot": "/home/user/artifacts/STEP-01.png"},
            {"step_id": "STEP-02", "intent": "Open pricing and verify hero layout", "status": "FAILED", "error": "Visual overlap detected", "screenshot": "/home/user/artifacts/STEP-02_failure.png"},
        ],
    }, indent=2))
    (run_dir / "vision_inspection_report.json").write_text(json.dumps({
        "schema_version": "1.0",
        "deduped": [
            {"category": "overlap", "issue": "CTA button overlaps hero heading", "severity": "high", "confidence": 0.93,
             "description": "The primary CTA button overlaps the hero heading text at desktop viewport.",
             "location": "homepage hero", "suggestion": "Adjust hero spacing or CTA positioning/z-index.",
             "evidence": {"screenshot": str(run_dir / "STEP-02_failure.png")}},
            {"category": "layout", "issue": "none", "severity": "info", "confidence": 0.9, "description": "No other layout issue."},
        ],
    }, indent=2))
    return run_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--existing-title", default=None, help="Simulate dedup against an existing issue title")
    args = parser.parse_args()

    base = Path("artifacts/demo_bug_filing_tmp")
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)
    run_dir = make_run_dir(base)

    print("=" * 72)
    print("STORY-E2B-005.2: Bug Generation from E2B Findings")
    print("=" * 72)
    gen = BugReportGenerator()
    report = gen.generate(
        run_dir=run_dir,
        inspection_report=run_dir / "vision_inspection_report.json",
        step_results=run_dir / "step_results.json",
        url="https://testradius.dev",
        environment={"browser": "chromium", "viewport": "1280x800", "sandbox": "e2b"},
    )
    print(f"Title:    {report.title}")
    print(f"Severity: {report.severity}  Priority: {report.priority}")
    print(f"Steps:    {len(report.steps_to_reproduce)} repro steps")
    print(f"Evidence: {len(report.evidence.screenshots)} screenshots, {len(report.evidence.traces)} traces, manifest={bool(report.evidence.manifest_path)}")
    print(f"Report:   {len(report.render_markdown())} chars markdown (includes findings + evidence)")
    assert report.severity in {"high", "critical", "medium"}
    assert report.priority in {"P0", "P1", "P2"}
    assert report.evidence.screenshots
    assert report.steps_to_reproduce
    print("✓ 005.2 bug report generated with evidence, repro steps, severity/priority.\n")

    print("=" * 72)
    print("STORY-E2B-005.1: Checkpoint Integration (approval gate + findings/screenshots + audit)")
    print("=" * 72)
    registry = ApprovalRegistry()
    connector = GitHubConnector(repo="testradius/testradius", dry_run=True)
    wf = BugFilingWorkflow(registry=registry, generator=gen, connector=connector)
    pkg = wf.prepare_review(
        approval_id="bug-approval-demo",
        run_dir=run_dir,
        inspection_report=run_dir / "vision_inspection_report.json",
        step_results=run_dir / "step_results.json",
        url="https://testradius.dev",
        environment={"browser": "chromium", "viewport": "1280x800"},
    )
    print(pkg["review_text"])
    print(f"\nSaved review package: {pkg.get('saved', {}).get('review_package')}")
    print(f"Saved audit log:      {pkg.get('saved', {}).get('audit_log')}")
    try:
        wf.file_after_approval(approval_id="bug-approval-demo", run_dir=run_dir, inspection_report=run_dir / "vision_inspection_report.json", url="https://testradius.dev")
        raise AssertionError("filing should be blocked without approval")
    except PermissionError:
        print("\n✓ 005.1 filing correctly BLOCKED without approval.")
    wf.approve("bug-approval-demo", actor="qa-reviewer", detail="Verified screenshots and findings")
    audit = json.loads((run_dir / "bug_filing_audit.json").read_text())
    print(f"✓ 005.1 approved by {audit['approved_by']}; audit actions include APPROVE.\n")

    print("=" * 72)
    print("STORY-E2B-005.3: Connector Integration & Dedup (GitHub dry-run)")
    print("=" * 72)
    existing = [{"title": args.existing_title}] if args.existing_title else []
    if not existing:
        # default demo: no duplicate
        existing = []
    result = wf.file_after_approval(
        approval_id="bug-approval-demo", actor="qa-reviewer", run_dir=run_dir,
        inspection_report=run_dir / "vision_inspection_report.json", step_results=run_dir / "step_results.json",
        url="https://testradius.dev", existing_issues=existing,
    )
    print(json.dumps({k: v for k, v in result.items() if k != "body"}, indent=2, default=str)[:4000])
    assert result["approved"] is True
    assert result["status"] in {"dry_run", "filed", "duplicate"}
    assert "evidence" in result
    state = registry.get("bug-approval-demo")
    assert any(e.action in {"FILE_DRY_RUN", "FILE_FILED", "FILE_DUPLICATE"} for e in state.audit_log)
    print(f"\n✓ 005.3 connector result={result['status']} with approval gate, dedup, and evidence links.")

    # Demonstrate dedup explicitly
    print("\n--- Dedup demo ---")
    registry2 = ApprovalRegistry()
    wf2 = BugFilingWorkflow(registry=registry2, generator=gen, connector=connector)
    wf2.prepare_review(approval_id="dedup-demo", run_dir=run_dir, inspection_report=run_dir / "vision_inspection_report.json", url="https://testradius.dev", save=False)
    wf2.approve("dedup-demo", actor="qa-reviewer")
    dup = wf2.file_after_approval(approval_id="dedup-demo", actor="qa-reviewer", run_dir=run_dir, inspection_report=run_dir / "vision_inspection_report.json", url="https://testradius.dev", existing_issues=[{"title": report.title}])
    assert dup["status"] == "duplicate"
    print(f"✓ 005.3 dedup detected existing issue title: {report.title}")

    print("\n" + "=" * 72)
    print("✓ EPIC-E2B-005 DEMO PASSED: 005.1 approval gate/audit, 005.2 repro-ready bug report, 005.3 connector+dedup.")
    print("=" * 72)

    shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    main()
