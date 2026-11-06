#!/usr/bin/env python3
"""Tiny compiled-plan computer-use spike (STORY-E2B-008.4.3).

Default: **safe mock mode** (MockComputerUsePrimitives + MockGeminiComputerUseClient).
Executes the first 1–3 steps of a compiled plan end-to-end (screenshot → propose →
validate → execute → evidence) and writes ``spike_report.json``.

Live mode (env-dependent, requires E2B desktop template + Gemini key):
  E2B_API_KEY=... E2B_API_URL=http://8.231.230.69:3000 E2B_DOMAIN=8.231.230.69.nip.io:3002 \
  GEMINI_API_KEY=... python scripts/test_e2b_gemini_computer_use.py --live

Usage:
  python scripts/test_e2b_gemini_computer_use.py
  python scripts/test_e2b_gemini_computer_use.py --plan evals/fixtures/computer_use_tiny_plan.json --artifacts-dir artifacts/computer_use_spike
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.computer_use import ComputerUseConfig, ComputerUseSpikeRunner
from harness.computer_use.gemini_client import GeminiComputerUseClient, MockGeminiComputerUseClient
from harness.computer_use.primitives import E2BDesktopPrimitives, MockComputerUsePrimitives

TINY = Path(__file__).resolve().parent.parent / "evals" / "fixtures" / "computer_use_tiny_plan.json"


def _run_mock(args) -> None:
    primitives = MockComputerUsePrimitives(width=1440, height=900)
    client = MockGeminiComputerUseClient(script=[
        {"action_type": "navigate", "url": "https://testradius.dev/", "reason": "Open homepage"},
        {"action_type": "assert", "reason": "Hero visible and page loaded"},
        {"action_type": "stop", "reason": "done"},
    ])
    runner = ComputerUseSpikeRunner(primitives=primitives, gemini_client=client, artifacts_dir=Path(args.artifacts_dir))
    plan = json.loads(Path(args.plan).read_text())
    report = runner.run(run_id=args.run_id, plan=plan, max_steps=args.max_steps)
    print(json.dumps(report.to_dict(), indent=2))
    assert report.status == "COMPLETED", report.error
    print(f"\nSpike report: {Path(args.artifacts_dir)/args.run_id/'spike_report.json'}")
    print("✓ 008.4 mock spike passed: tiny compiled plan executed with screenshots + validated actions.")


def _run_live(args) -> None:
    cfg = ComputerUseConfig()
    if not cfg.resolve_e2b_key():
        raise SystemExit("E2B_API_KEY not set (required for --live)")
    if not cfg.resolve_gemini_key():
        raise SystemExit("GEMINI_API_KEY/GOOGLE_API_KEY not set (required for --live)")
    from harness.sandbox.e2b_provider import E2BSandboxProvider

    provider = E2BSandboxProvider()
    sandbox_id = provider.create(template=cfg.e2b_template, timeout=cfg.sandbox_timeout_s, cpu_count=cfg.e2b_cpu, memory_mb=cfg.e2b_memory_mb)
    print(f"Created E2B desktop sandbox: {sandbox_id} (template={cfg.e2b_template})")
    try:
        # Desktop startup on virtual display (template script); non-fatal if missing.
        provider.run_command(sandbox_id, "bash ~/start-desktop.sh 2>&1 || true", timeout=60)
        primitives = E2BDesktopPrimitives(provider=provider, sandbox_id=sandbox_id, display=cfg.display, width=cfg.screen_width, height=cfg.screen_height)
        client = GeminiComputerUseClient(model=cfg.gemini_model, api_key=cfg.resolve_gemini_key())
        runner = ComputerUseSpikeRunner(primitives=primitives, gemini_client=client, artifacts_dir=Path(args.artifacts_dir))
        plan = json.loads(Path(args.plan).read_text())
        report = runner.run(run_id=args.run_id, plan=plan, max_steps=args.max_steps)
        print(json.dumps(report.to_dict(), indent=2))
    finally:
        provider.kill(sandbox_id)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--plan", default=str(TINY))
    p.add_argument("--run-id", default="run-computer-use-spike")
    p.add_argument("--artifacts-dir", default="artifacts/computer_use_spike")
    p.add_argument("--max-steps", type=int, default=3)
    p.add_argument("--live", action="store_true", help="Use real E2B desktop + Gemini (env-dependent)")
    args = p.parse_args()
    if args.live:
        _run_live(args)
    else:
        _run_mock(args)


if __name__ == "__main__":
    main()
