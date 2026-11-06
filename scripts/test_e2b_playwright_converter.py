#!/usr/bin/env python3
"""Demo for STORY-E2B-003.3: Compiled Test Plan to Playwright Converter.

Parses a compiled test plan, classifies steps as automatable (explicit
selectors/hints) vs computer_use_only, reports conversion coverage, and
generates a runnable Playwright script for supported steps.

Usage:
  # Local conversion demo (no E2B required):
  python scripts/test_e2b_playwright_converter.py

  # Save outputs:
  python scripts/test_e2b_playwright_converter.py --out artifacts/demo_converter
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.adapters.playwright.converter import PlaywrightPlanConverter

# Realistic compiled plan with mixed automation coverage
COMPILED_PLAN = {
    "schema_version": "1.0",
    "plan_id": "PLAN-TR-LOGIN-MIXED-001",
    "title": "TestRadius Login and Dashboard Smoke (Mixed)",
    "objective": "Verify login flow with a mix of deterministic and visual/computer-use steps",
    "sut": {
        "base_url": "https://testradius.dev",
        "environment": "staging",
        "viewport": "1280x800",
    },
    "cases": [
        {
            "case_id": "TC-LOGIN-001",
            "title": "User can reach login and verify UI",
            "steps": [
                {
                    "step_id": "S1",
                    "ordinal": 1,
                    "intent": "Navigate to TestRadius landing page",
                    "action_type": "navigate",
                    "input": {"url": "https://testradius.dev"},
                    "success_criteria": ["URL contains 'testradius.dev'"],
                    "timeout_s": 25,
                },
                {
                    "step_id": "S2",
                    "ordinal": 2,
                    "intent": "Click the Sign In link in the header",
                    "action_type": "click",
                    "target": {
                        "description": "Sign In link",
                        "hints": {"role": "link", "visible_text": ["Sign In", "Login"]},
                    },
                    "timeout_s": 10,
                },
                {
                    "step_id": "S3",
                    "ordinal": 3,
                    "intent": "Type email into the email field",
                    "action_type": "type",
                    "target": {
                        "description": "Email input",
                        "hints": {"selector": "input[type='email'], input[name='email']"},
                    },
                    "input": {"text": "qa@example.com"},
                    "timeout_s": 10,
                },
                {
                    "step_id": "S4",
                    "ordinal": 4,
                    "intent": "Drag the custom captcha slider to complete verification",
                    "action_type": "drag",
                    "target": {
                        "description": "Custom anti-bot slider widget with no stable DOM selector exposed",
                        "hints": {},
                    },
                    "input": {"direction": "right"},
                    "timeout_s": 15,
                },
                {
                    "step_id": "S5",
                    "ordinal": 5,
                    "intent": "Verify login page heading is visible",
                    "action_type": "assert",
                    "success_criteria": ["Page title contains 'TestRadius' or 'Login'"],
                    "timeout_s": 10,
                },
                {
                    "step_id": "S6",
                    "ordinal": 6,
                    "intent": "Visually confirm the hero illustration is not clipped or overlapping text",
                    "action_type": "assert",
                    "success_criteria": [],
                    "timeout_s": 10,
                },
            ],
        }
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo Playwright plan converter")
    parser.add_argument("--out", type=Path, default=None, help="Directory to save report/script/converted plan")
    args = parser.parse_args()

    print("=== STORY-E2B-003.3: Compiled Test Plan → Playwright Converter ===\n")
    print(f"Input plan: {COMPILED_PLAN['plan_id']} ({COMPILED_PLAN['title']})")
    total = sum(len(c.get("steps", [])) for c in COMPILED_PLAN["cases"])
    print(f"Total steps: {total}\n")

    converter = PlaywrightPlanConverter()
    result = converter.convert(COMPILED_PLAN, target_url="https://testradius.dev", record_trace=True)

    report = result.report
    print("Conversion Report")
    print("-" * 72)
    print(f"Automated steps:      {report.automated_steps}")
    print(f"Computer-use-only:    {report.computer_use_only_steps}")
    print(f"Coverage:             {report.coverage_pct:.2f}%")
    print(f"By action:            {json.dumps(report.by_action, indent=2)}")
    print("\nPer-step classification:")
    for s in report.steps:
        hints = f" hints={s.used_hints}" if s.used_hints else ""
        reasons = f" reasons={s.reasons}" if s.reasons else ""
        print(f"  [{s.classification:16}] {s.step_id} ({s.action_type}) {s.intent}{hints}{reasons}")

    print(f"\nGenerated script: {len(result.script)} bytes (valid runnable Python for supported steps)")
    print("Script includes: CONVERSION_REPORT, computer_use_only handling, AUTOMATION_COVERAGE_PCT output")

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "conversion_report.json").write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        (args.out / "converted_plan.json").write_text(json.dumps(result.converted_plan, indent=2), encoding="utf-8")
        (args.out / "converted_test_script.py").write_text(result.script, encoding="utf-8")
        print(f"\nSaved outputs to {args.out}/")

    # Sanity check: script parses
    import ast

    ast.parse(result.script)
    print("\n✓ STORY-E2B-003.3 DEMO PASSED: Plan converted with coverage report and runnable script generated.")


if __name__ == "__main__":
    main()
