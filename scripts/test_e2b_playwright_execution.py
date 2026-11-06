#!/usr/bin/env python3
"""Smoke test demonstrating Playwright script generation & execution from a compiled test plan.

STORY-E2B-003.2:
- Takes a compiled test plan with multiple steps (navigate, assert, screenshot)
- Uses PlaywrightScriptGenerator to generate an async Playwright runner
- Uploads and executes the script via E2BExecutor
- Collects step_results.json, screenshots, and trace
- Reports step-by-step execution status and duration

Usage:
  # Fast mock mode (demonstrates generation, delivery, and artifact collection instantly):
  python scripts/test_e2b_playwright_execution.py --mock

  # Live E2B mode:
  export E2B_API_KEY="..." E2B_API_URL="http://8.231.230.69:3000"
  export E2B_DOMAIN="8.231.230.69.nip.io:3002"
  python scripts/test_e2b_playwright_execution.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Ensure repo root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.adapters.playwright.generator import PlaywrightScriptGenerator
from harness.execution.base import ExecutorConfig
from harness.execution.e2b import E2BExecutor
from harness.sandbox.base import BaseSandboxProvider

COMPILED_PLAN = {
    "schema_version": "1.0",
    "plan_id": "PLAN-PLAYWRIGHT-SMOKE",
    "title": "TestRadius Landing Page Verification",
    "objective": "Verify landing page loads and title matches TestRadius",
    "sut": {
        "base_url": "https://testradius.dev",
        "environment": "staging",
        "viewport": "1280x800",
    },
    "cases": [
        {
            "case_id": "TC-LANDING-01",
            "title": "Homepage Load & Title",
            "steps": [
                {
                    "step_id": "STEP-01",
                    "ordinal": 1,
                    "intent": "Navigate to the landing page",
                    "action_type": "navigate",
                    "input": {"url": "https://testradius.dev"},
                    "timeout_s": 25,
                    "evidence": {"screenshot_after": True},
                },
                {
                    "step_id": "STEP-02",
                    "ordinal": 2,
                    "intent": "Verify page title",
                    "action_type": "assert",
                    "success_criteria": [
                        "Page title contains 'TestRadius'"
                    ],
                    "timeout_s": 10,
                    "evidence": {"screenshot_after": True},
                },
            ],
        }
    ],
}


class MockE2BDemoProvider(BaseSandboxProvider):
    """Mock provider simulating sandbox script execution and artifact generation."""

    def __init__(self):
        self.files: dict[tuple[str, str], bytes] = {}
        self.commands: list[str] = []

    def create(self, template: str = "playwright-chromium", timeout: int = 300, **kwargs) -> str:
        return "sbx-mock-demo"

    def kill(self, sandbox_id: str) -> bool:
        return True

    def run_command(self, sandbox_id: str, command: str, timeout: int = 60) -> dict:
        self.commands.append(command)
        if "echo READY" in command:
            return {"stdout": "READY", "stderr": "", "exit_code": 0}
        if "test -s" in command:
            return {"stdout": "OK", "stderr": "", "exit_code": 0}

        # Simulate test runner writing step_results.json and screenshots
        step_results = {
            "plan_id": "PLAN-PLAYWRIGHT-SMOKE",
            "status": "PASSED",
            "total_steps": 2,
            "passed_steps": 2,
            "failed_steps": 0,
            "steps": [
                {
                    "step_id": "STEP-01",
                    "case_id": "TC-LANDING-01",
                    "intent": "Navigate to the landing page",
                    "action_type": "navigate",
                    "status": "PASSED",
                    "duration_ms": 420,
                    "screenshot": "/home/user/artifacts/STEP-01.png",
                    "error": None,
                },
                {
                    "step_id": "STEP-02",
                    "case_id": "TC-LANDING-01",
                    "intent": "Verify page title",
                    "action_type": "assert",
                    "status": "PASSED",
                    "duration_ms": 85,
                    "screenshot": "/home/user/artifacts/STEP-02.png",
                    "error": None,
                },
            ],
        }
        self.files[(sandbox_id, "/home/user/artifacts/step_results.json")] = json.dumps(step_results).encode("utf-8")
        self.files[(sandbox_id, "/home/user/artifacts/STEP-01.png")] = b"\x89PNG\r\n\x1a\n(fake-step-01-screenshot)"
        self.files[(sandbox_id, "/home/user/artifacts/STEP-02.png")] = b"\x89PNG\r\n\x1a\n(fake-step-02-screenshot)"
        self.files[(sandbox_id, "/home/user/artifacts/trace.zip")] = b"PK\x03\x04(fake-trace-zip)"

        return {
            "stdout": "RESULTS_FILE=/home/user/artifacts/step_results.json\nOVERALL_STATUS=PASSED\nPASSED=2/2\n",
            "stderr": "",
            "exit_code": 0,
        }

    def upload_file(self, sandbox_id: str, path: str, content: bytes) -> bool:
        self.files[(sandbox_id, path)] = content
        return True

    def download_file(self, sandbox_id: str, path: str) -> bytes:
        return self.files.get((sandbox_id, path), b"")

    def is_running(self, sandbox_id: str) -> bool:
        return True


def main() -> None:
    use_mock = "--mock" in sys.argv or not os.environ.get("E2B_API_KEY")
    mode_label = "MOCK PROVIDER" if use_mock else "LIVE E2B"

    print(f"=== Playwright Script Generation & Execution Demo ({mode_label}) ===\n")

    # 1. Script Generation
    print("1. Generating Playwright script from compiled plan schema...")
    generator = PlaywrightScriptGenerator()
    script = generator.generate(
        plan=COMPILED_PLAN,
        target_url="https://testradius.dev",
        record_trace=True,
    )
    print(f"✓ Generated script ({len(script)} bytes). Preview:")
    for line in script.splitlines()[:16]:
        print(f"   {line}")
    print("   ...\n")

    # 2. Execution
    template = os.environ.get("E2B_PLAYWRIGHT_TEMPLATE", "playwright-chromium")
    artifacts_dir = Path("artifacts") / "demo_playwright_execution"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    cfg = ExecutorConfig(
        run_id="run-pw-demo-001",
        target_url="https://testradius.dev",
        plan=COMPILED_PLAN,
        artifacts_dir=artifacts_dir,
        capture_traces=True,
        metadata={"template": template, "env": "staging", "allowed_domains": ["testradius.dev"]},
    )

    executor = E2BExecutor(cfg)
    if use_mock:
        executor.provider = MockE2BDemoProvider()

    try:
        print(f"2. Executing plan via E2BExecutor (template={template})...")
        res = executor.execute_plan()

        print(f"\nExecution finished with status: {res.status.value}")
        print(f"Total steps executed: {len(res.steps)}")
        for step in res.steps:
            print(f"  [{step.status}] {step.step_id}: {step.title} ({step.duration_ms}ms)")
            if step.error:
                print(f"      ERROR: {step.error}")
            if step.screenshots:
                print(f"      Screenshots: {step.screenshots}")

        print(f"\n3. Artifacts collected:")
        print(f"  Screenshots count: {len(res.screenshots)}")
        print(f"  Trace path:        {res.trace_path}")
        print(f"  Summary:           {json.dumps(res.summary, indent=2)}")

        if res.status.value == "COMPLETED" and len(res.steps) == 2:
            print("\n✓ STORY-E2B-003.2 DEMO PASSED: Playwright script generated from compiled plan executed successfully.")
        else:
            print("\n❌ Execution completed with unexpected status or step count.")
            sys.exit(1)
    finally:
        print("\n4. Cleaning up...")
        executor.cleanup()
        # Clean demo artifacts directory
        import shutil
        shutil.rmtree(artifacts_dir, ignore_errors=True)
        print("✓ Cleanup complete.")


if __name__ == "__main__":
    main()
