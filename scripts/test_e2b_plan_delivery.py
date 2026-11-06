#!/usr/bin/env python3
"""Smoke test for delivering a compiled test plan and runtime config to an E2B sandbox.

STORY-E2B-003.1:
- Delivers compiled_test_plan.json and runtime_config.json into /home/user
- Verifies files exist and are non-empty
- Verifies secret redaction
- Runs a check in the sandbox proving it can read the compiled plan without any raw context upload

Usage:
  export E2B_API_KEY="..." E2B_API_URL="http://8.231.230.69:3000"
  export E2B_DOMAIN="8.231.230.69.nip.io:3002"
  python scripts/test_e2b_plan_delivery.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Ensure workspace root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.sandbox.delivery import (
    RuntimeConfig,
    SecretExposureError,
    deliver_plan_and_config,
)
from harness.sandbox.e2b_provider import E2BSandboxProvider

SAMPLE_PLAN = {
    "schema_version": "1.0",
    "plan_id": "PLAN-DEMO-003.1",
    "title": "Smoke Test for Compiled Plan Delivery",
    "objective": "Verify compiled plan delivery to E2B sandbox without raw context",
    "sut": {
        "base_url": "https://testradius.dev",
        "environment": "staging",
    },
    "preconditions": ["Network reachable"],
    "cases": [
        {
            "case_id": "TC-01",
            "title": "Delivery Verification",
            "steps": [
                {
                    "step_id": "S1",
                    "ordinal": 1,
                    "intent": "Read delivered compiled plan",
                    "action_type": "assert",
                    "target": {"description": "Local filesystem file"},
                    "success_criteria": ["File exists and valid JSON"],
                }
            ],
        }
    ],
}


def main() -> None:
    api_key = os.environ.get("E2B_API_KEY")
    if not api_key:
        print("ERROR: E2B_API_KEY is not set.")
        sys.exit(1)

    print("Initializing E2BSandboxProvider...")
    provider = E2BSandboxProvider()

    # 1. Test secret exposure prevention locally first
    print("\n1. Testing secret-exposure guard...")
    bad_plan = dict(SAMPLE_PLAN)
    bad_plan["leaked_key"] = "AKIA1234567890ABCDEF"
    try:
        deliver_plan_and_config(
            provider=provider,
            sandbox_id="dummy",
            plan=bad_plan,
            runtime_config=RuntimeConfig("run-test", "https://testradius.dev"),
            strict_secrets=True,
            verify=False,
        )
        print("❌ Expected SecretExposureError but none was raised!")
        sys.exit(1)
    except SecretExposureError as e:
        print(f"✓ Secret exposure blocked as expected: {e}")

    # 2. Create sandbox and deliver clean plan
    print("\n2. Creating E2B sandbox (base template)...")
    template = os.environ.get("E2B_TEMPLATE", "base")
    sandbox_id = provider.create(template=template, timeout=300)
    print(f"✓ Created sandbox: {sandbox_id}")

    try:
        runtime_config = RuntimeConfig(
            run_id="run-delivery-smoke-001",
            target_url="https://testradius.dev",
            env="staging",
            allowed_domains=["testradius.dev"],
            env_vars={"BASE_URL": "https://testradius.dev"},
            timeout_s=300,
            metadata={"test_mode": "compiled_plan_delivery"},
        )

        print("\n3. Delivering compiled plan and runtime config...")
        res = deliver_plan_and_config(
            provider=provider,
            sandbox_id=sandbox_id,
            plan=SAMPLE_PLAN,
            runtime_config=runtime_config,
            destination_dir="/home/user",
            verify=True,
        )

        print(f"✓ Delivery successful!")
        print(f"  Plan path:   {res.plan_path} ({res.plan_bytes} bytes)")
        print(f"  Config path: {res.config_path} ({res.config_bytes} bytes)")
        print(f"  Verified:    {res.verified}")
        print(f"  Plan ID:     {res.plan_id}")

        print("\n4. Verifying sandbox can read delivered plan without raw context...")
        verify_cmd = (
            "python3 -c \""
            "import json; "
            "p = json.load(open('/home/user/compiled_test_plan.json')); "
            "c = json.load(open('/home/user/runtime_config.json')); "
            "print('SANDBOX_PLAN_ID=' + p['plan_id']); "
            "print('SANDBOX_CASES_COUNT=' + str(len(p['cases']))); "
            "print('SANDBOX_RUN_ID=' + c['run_id']); "
            "\""
        )
        out = provider.run_command(sandbox_id, verify_cmd, timeout=30)
        stdout = out.get("stdout", "")
        stderr = out.get("stderr", "")
        print(stdout)
        if stderr:
            print("STDERR:", stderr)

        if "SANDBOX_PLAN_ID=PLAN-DEMO-003.1" in stdout and "SANDBOX_RUN_ID=run-delivery-smoke-001" in stdout:
            print("\n✓ STORY-E2B-003.1 DEMO PASSED: Sandbox received and parsed compiled plan and config.")
        else:
            print("\n❌ Verification failed; stdout did not match expected tokens.")
            sys.exit(1)

    finally:
        print("\n5. Cleaning up sandbox...")
        provider.kill(sandbox_id)
        print("✓ Sandbox killed.")


if __name__ == "__main__":
    main()
