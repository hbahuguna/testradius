#!/usr/bin/env python3
"""Demo for STORY-E2B-004.3: Multi-Round Self-Inspection.

Runs 2+ vision inspection rounds on screenshot artifact(s), logs each round,
deduplicates findings, and saves an inspection report.

Usage:
  python scripts/test_e2b_vision_inspection.py
  python scripts/test_e2b_vision_inspection.py --screenshot artifacts/run-<id>/page.png --rounds 2
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.vision import SelfInspector, VisionClient
from harness.vision.providers import MockVisionProvider


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot", type=Path, default=None)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--model", default="mock")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    temp = None
    screenshot = args.screenshot
    if not screenshot:
        temp = Path("artifacts/demo_vision_inspection_tmp")
        if temp.exists():
            shutil.rmtree(temp)
        temp.mkdir(parents=True)
        screenshot = temp / "hero_contrast_issue.png"
        screenshot.write_bytes(b"\x89PNG\r\n\x1a\n(demo)")

    client = VisionClient(model=args.model, provider=MockVisionProvider() if args.model == "mock" else None)
    inspector = SelfInspector(rounds=args.rounds, client=client)
    report = inspector.inspect(str(screenshot), url="https://testradius.dev", viewport="1280x800")

    print("=== STORY-E2B-004.3: Multi-Round Self-Inspection Demo ===\n")
    print(f"Screenshot: {screenshot}")
    print(f"Rounds:     {report['summary']['round_count']}")
    for r in report["rounds"]:
        print(f"\nRound {r['round']} [{r['purpose']}] model={r.get('provider')}:{r.get('model')}")
        print(f"  started:   {r['started_at']}")
        print(f"  completed: {r['completed_at']}")
        print(f"  summary:   {r.get('summary')}")
        print(f"  findings:  {len(r.get('findings', []))} (actionable: {len(r.get('actionable_findings', []))})")

    print("\nDeduped findings:")
    for f in report["deduped"]:
        print(f"  - [{f.get('category')}] {f.get('issue')} severity={f.get('severity')} confidence={float(f.get('confidence') or 0):.2f} @ {f.get('location') or 'n/a'}")

    print("\nSummary:", json.dumps(report["summary"], indent=2))

    out = args.out or (Path(screenshot).parent / "vision_inspection_report.json")
    SelfInspector.save_report(report, out)
    print(f"\nInspection report saved: {out}")

    assert len(report["rounds"]) >= 2
    assert all("purpose" in r and "started_at" in r for r in report["rounds"])
    assert "deduped" in report and "summary" in report
    print("\n✓ STORY-E2B-004.3 DEMO PASSED: 2+ inspection rounds logged with deduped findings and report.")

    if temp and temp.exists():
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    main()
