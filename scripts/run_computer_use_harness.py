#!/usr/bin/env python3
"""Harness integration: checkpoints + findings + bug review (008.6).

Runs a compiled plan through ComputerUseHarnessRunner (live when keys present
+ --live, else demo mock) and shows:
- plan checkpoint (prod blocked until approved; spike allowed)
- failed step -> reviewable finding (expected vs observed, screenshots, trace, source refs)
- bug review package prepared; filing BLOCKED until approval; after approval -> dry-run draft ticket.

Usage:
  python scripts/run_computer_use_harness.py --plan "$RUN_ROOT/02-compile/run-live-compile-001/compiled_test_plan.json" --live
  python scripts/run_computer_use_harness.py --plan evals/fixtures/compiled_test_plan.valid.json
  python scripts/run_computer_use_harness.py --approve-bug
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.checkpoints import ApprovalRegistry
from harness.computer_use.integration import ComputerUseHarnessRunner
from harness.connectors import GitHubConnector

GOLDEN = Path(__file__).resolve().parent.parent / "evals" / "fixtures" / "compiled_test_plan.valid.json"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--plan", default=str(GOLDEN), help="Compiled plan JSON (default: golden fixture)")
    p.add_argument("--artifacts-dir", default="artifacts/computer_use_harness_demo")
    p.add_argument("--run-id", default="run-cu-harness-001")
    p.add_argument("--mode", default="local_spike", choices=["local_spike", "production"])
    p.add_argument("--live", action="store_true", help="Use live E2B/Gemini (requires keys); else demo mock path")
    p.add_argument("--approve-plan", action="store_true", help="Approve plan checkpoint (spike mode demos)")
    p.add_argument("--approve-bug", action="store_true", help="Approve bug review then file dry-run draft")
    args = p.parse_args()

    plan = json.loads(Path(args.plan).read_text())
    runner = ComputerUseHarnessRunner(artifacts_dir=args.artifacts_dir, registry=ApprovalRegistry())
    meta: dict = {"mode": args.mode}
    if not args.live:
        meta.update({"mock": True, "assess_pass": False})  # force a reproducible finding (demo)
    report = runner.run_compiled_plan(run_id=args.run_id, plan=plan, mode=args.mode, metadata=meta)
    print(json.dumps({"run_id": report.get("run_id"), "status": report.get("status"), "findings": len(report.get("findings") or []), "bug_review": report.get("bug_review")}, indent=2))
    run_dir = Path(args.artifacts_dir) / args.run_id
    findings = json.loads((run_dir / "findings.json").read_text())
    print(f"\nFirst finding keys: {sorted(findings[0].keys()) if findings else 'none'}")
    if findings:
        print(f"step={findings[0].get('step_id')} expected={findings[0].get('expected')[:1]} source_refs={findings[0].get('source_refs')[:1]}")
    print(f"\nBug review: {(run_dir / 'bug_review_package.json').exists()} | bug_report: {(run_dir / 'bug_report.md').exists()}")

    if args.approve_bug and report.get("bug_review"):
        runner.bug_workflow.approve(report["bug_review"]["approval_id"], actor="qa-lead", detail="Demo approval")
        result = runner.bug_workflow.file_after_approval(
            approval_id=report["bug_review"]["approval_id"], actor="qa-lead", run_dir=run_dir,
            connector=GitHubConnector(repo="testradius/web", dry_run=True),
        )
        print(json.dumps({"filed": result.get("status"), "url": result.get("url"), "approved": result.get("approved")}, indent=2))
    print("\n✓ 008.6 demo passed: checkpointed run with reviewable finding (no filing without approval).")


if __name__ == "__main__":
    main()
