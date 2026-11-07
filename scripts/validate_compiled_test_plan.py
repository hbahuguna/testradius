#!/usr/bin/env python3
"""Demo: compiled test plan validation/quality gate (STORY-E2B-008.2).

Shows a high-quality plan passing and an invalid/vague plan failing.
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.testplan import CompiledPlanValidator

FIXTURE = Path(__file__).resolve().parent.parent / "evals" / "fixtures" / "compiled_test_plan.valid.json"


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Validate a compiled test plan")
    p.add_argument("--plan", default=str(FIXTURE), help="Compiled plan JSON (default: golden fixture)")
    args = p.parse_args()
    valid = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    validator = CompiledPlanValidator()

    print("=" * 72)
    print("STORY-E2B-008.2: Compiled Test Plan Schema & Quality Gate")
    print("=" * 72)

    ok = validator.validate(valid, mode="local_spike")
    print("\n[valid/local_spike]")
    print(json.dumps({"ok": ok.ok, "errors": [e.code for e in ok.errors], "warnings": [w.code for w in ok.warnings], "review_status": valid["quality_gate"]["review_status"]}, indent=2))
    assert ok.ok

    prod_draft = deepcopy(valid)
    prod_draft["quality_gate"]["review_status"] = "draft"
    blocked = validator.validate(prod_draft, mode="production")
    print("\n[draft/production]")
    print(json.dumps({"ok": blocked.ok, "errors": [e.code for e in blocked.errors]}, indent=2))
    assert not blocked.ok and any(e.code == "review_not_approved" for e in blocked.errors)

    bad = deepcopy(valid)
    bad["sut"]["base_url"] = ""
    bad["preconditions"] = []
    bad["constraints"]["allowed_domains"] = []
    bad["cases"][0]["steps"][0]["success_criteria"] = ["verify it works"]
    bad["cases"][0]["steps"][0]["evidence"] = {"screenshot_on_failure": False, "action_trace": False, "screenshot_after": False, "screenshot_before": False, "dom_text": False}
    bad["cases"][0]["steps"][0]["input"] = {"password": "plaintext-secret"}
    failed = validator.validate(bad, mode="local_spike")
    print("\n[invalid/vague/secret]")
    print(json.dumps({"ok": failed.ok, "error_codes": sorted({e.code for e in failed.errors}), "sample_issues": [e.model_dump() for e in failed.errors[:4]]}, indent=2))
    expected = {"missing_target", "invalid_target", "missing_preconditions", "missing_allowed_domains", "vague_success_criteria", "missing_evidence", "inline_secret"}
    assert expected & {e.code for e in failed.errors}

    print("\n✓ 008.2 demo passed: high-quality plan passes; draft blocked in production; invalid/vague/secret plan rejected.")
    print("=" * 72)


if __name__ == "__main__":
    main()
