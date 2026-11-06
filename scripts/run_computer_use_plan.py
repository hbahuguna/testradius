#!/usr/bin/env python3
"""E2E computer-use runner demo: golden compiled plan → actions → evidence (008.5.4).

Default: **safe mock mode** (no live E2B/Gemini). Executes `evals/fixtures/compiled_test_plan.valid.json`
against https://testradius.dev via the structured per-step loop (Option B).
Writes `action_trace.jsonl`, step screenshots, `step_results.json`, `run_summary.json`.

Live mode (env-dependent, requires E2B desktop template + Gemini key):
  E2B_API_KEY=... E2B_API_URL=http://8.231.230.69:3000 E2B_DOMAIN=8.231.230.69.nip.io:3002 \\
  GEMINI_API_KEY=... python scripts/run_computer_use_plan.py --live

Usage:
  python scripts/run_computer_use_plan.py
  python scripts/run_computer_use_plan.py --plan evals/fixtures/compiled_test_plan.valid.json --artifacts-dir artifacts/run-cu-e2e --run-id run-cu-e2e-001 --mode local_spike
  python scripts/run_computer_use_plan.py --loop whole_plan  # Option A non-default spike mode
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.computer_use import ComputerUseRunner
from harness.computer_use.gemini_client import GeminiComputerUseClient, MockGeminiComputerUseClient
from harness.computer_use.primitives import E2BDesktopPrimitives, MockComputerUsePrimitives

GOLDEN = Path(__file__).resolve().parent.parent / "evals" / "fixtures" / "compiled_test_plan.valid.json"


def _mock_client():
    return MockGeminiComputerUseClient(script=[
        {"action_type": "navigate", "url": "https://testradius.dev/", "reason": "Open homepage"},
        {"action_type": "assert", "reason": "CTA visible in hero"},
        {"action_type": "click", "x": 720, "y": 420, "reason": "Click primary CTA"},
    ])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--plan", default=str(GOLDEN))
    p.add_argument("--run-id", default="run-cu-e2e-001")
    p.add_argument("--artifacts-dir", default="artifacts")
    p.add_argument("--mode", default="local_spike", choices=["local_spike", "production"])
    p.add_argument("--loop", default="per_step", choices=["per_step", "whole_plan"], help="per_step = Option B (default); whole_plan = Option A non-default")
    p.add_argument("--live", action="store_true", help="Use real E2B desktop + Gemini (env-dependent)")
    args = p.parse_args()

    plan = json.loads(Path(args.plan).read_text())
    if args.live:
        from harness.computer_use import ComputerUseConfig
        from harness.sandbox.e2b_provider import E2BSandboxProvider

        cfg = ComputerUseConfig()
        if not cfg.resolve_e2b_key():
            raise SystemExit("E2B_API_KEY not set (required for --live)")
        if not cfg.resolve_gemini_key():
            raise SystemExit("GEMINI_API_KEY/GOOGLE_API_KEY not set (required for --live)")
        provider = E2BSandboxProvider()
        sandbox_id = provider.create(template=cfg.e2b_template, timeout=cfg.sandbox_timeout_s, cpu_count=cfg.e2b_cpu, memory_mb=cfg.e2b_memory_mb)
        print(f"Created E2B desktop sandbox: {sandbox_id}")
        try:
            provider.run_command(sandbox_id, "bash ~/start-desktop.sh 2>&1 || true", timeout=60)
            primitives = E2BDesktopPrimitives(provider=provider, sandbox_id=sandbox_id, display=cfg.display, width=cfg.screen_width, height=cfg.screen_height)
            client = GeminiComputerUseClient(model=cfg.gemini_model, api_key=cfg.resolve_gemini_key())
            runner = ComputerUseRunner(primitives=primitives, gemini_client=client, artifacts_dir=args.artifacts_dir, mode=args.mode)
            summary = runner.run(run_id=args.run_id, plan=plan, loop=args.loop)
            print(json.dumps(summary.to_dict(), indent=2))
        finally:
            provider.kill(sandbox_id)
    else:
        runner = ComputerUseRunner(primitives=MockComputerUsePrimitives(), gemini_client=_mock_client(), artifacts_dir=args.artifacts_dir, mode=args.mode)
        summary = runner.run(run_id=args.run_id, plan=plan, loop=args.loop)
        print(json.dumps({**summary.to_dict(), "loop": summary.mode}, indent=2))
        assert summary.total_steps > 0
        run_dir = Path(args.artifacts_dir) / args.run_id
        assert (run_dir / "action_trace.jsonl").exists()
        assert (run_dir / "run_summary.json").exists()
        assert (run_dir / "step_results.json").exists()
        print(f"\n✓ 008.5 demo passed (mock, loop={summary.mode}): action trace + step screenshots + run summary written.")
        print(f"Artifacts: {run_dir}")


if __name__ == "__main__":
    main()
