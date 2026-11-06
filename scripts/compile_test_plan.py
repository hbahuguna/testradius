#!/usr/bin/env python3
"""Demo/CLI: compile normalized context into a validated CompiledExecutionTestPlan (STORY-E2B-008.3).

Default demo uses a mocked Gemini generator (no API key required) and the golden
normalized context bundle. Pass --live with GEMINI_API_KEY/GOOGLE_API_KEY set to
use a real Gemini model (env-dependent; model/tool support should be verified).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.testplan import GeminiTestPlanCompiler

GOLDEN_CONTEXT = Path(__file__).resolve().parent.parent / "docs" / "examples" / "context_bundle.normalized.008.1.json"
GOLDEN_PLAN = Path(__file__).resolve().parent.parent / "evals" / "fixtures" / "compiled_test_plan.valid.json"


class MockGoldenGenerator:
    """Returns a valid compiled plan JSON (demo-safe, no live Gemini)."""

    model = "mock-gemini-demo"

    def generate(self, *, system: str, user: str) -> str:
        plan = json.loads(GOLDEN_PLAN.read_text())
        plan["plan_id"] = "ctp-0083-demo"
        plan["quality_gate"]["review_status"] = "draft"
        plan["quality_gate"]["compiled_by"] = "gemini(mock-demo)"
        plan["generator"] = {"model": self.model, "prompt_version": "testplan-compiler-v1", "compiler": "demo"}
        return json.dumps(plan)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--context", default=str(GOLDEN_CONTEXT), help="Normalized context bundle JSON")
    p.add_argument("--out-dir", default="artifacts/examples/008.3")
    p.add_argument("--run-id", default="run-0083-demo")
    p.add_argument("--base-url", default="https://testradius.dev")
    p.add_argument("--environment", default="staging")
    p.add_argument("--mode", default="local_spike", choices=["local_spike", "production"])
    p.add_argument("--live", action="store_true", help="Use real Gemini (requires GEMINI_API_KEY/GOOGLE_API_KEY)")
    args = p.parse_args()

    ctx = json.loads(Path(args.context).read_text())
    sut = {"base_url": args.base_url, "environment": args.environment, "browser": "chromium", "viewport": {"width": 1440, "height": 900}}
    generator = None if args.live else MockGoldenGenerator()
    compiler = GeminiTestPlanCompiler(generator=generator)
    res = compiler.compile(
        context_bundle=ctx,
        sut_config=sut,
        run_id=args.run_id,
        artifacts_dir=args.out_dir,
        mode=args.mode,
        provided_acs=ctx.get("acceptance_criteria") or [],
    )
    print(json.dumps(res.to_dict(), indent=2))
    if not res.ok:
        raise SystemExit(1)
    print(f"\nCompiled plan saved: {res.artifact_path}")


if __name__ == "__main__":
    main()
