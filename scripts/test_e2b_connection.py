#!/usr/bin/env python3
"""Test E2B connection to self-hosted instance."""
import os
from e2b import Sandbox


def main():
    api_key = os.environ.get("E2B_API_KEY")
    api_url = os.environ.get("E2B_API_URL")
    if not api_key:
        print("SKIP: E2B_API_KEY not set")
        return
    print(f"Connecting to E2B: {api_url or 'default'}")
    try:
        sbx = Sandbox.create(api_key=api_key, timeout=300)
        print(f"✓ Sandbox created: {sbx.sandbox_id}")
        sbx.kill()
        print("✓ Sandbox killed")
        print("\nConnection test PASSED")
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        raise


if __name__ == "__main__":
    main()
