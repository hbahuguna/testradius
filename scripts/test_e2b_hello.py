#!/usr/bin/env python3
"""Hello world test for E2B sandbox."""
import os
import time
from e2b import Sandbox


def main():
    print("Creating sandbox...")
    sandbox = Sandbox.create(timeout=300)
    print(f"Sandbox created: {sandbox.sandbox_id}")
    try:
        time.sleep(15)
        result = sandbox.commands.run('echo "Hello from the Manual QA Harness!"', timeout=30)
        print(f"Command output: {result.stdout}")
    except Exception as e:
        print(f"Command failed: {e}")
        print("Note: Self-hosted instance may have connectivity issues")
    finally:
        try:
            sandbox.kill()
            print("Sandbox killed.")
        except Exception as e:
            print(f"Kill failed: {e}")


if __name__ == "__main__":
    main()
