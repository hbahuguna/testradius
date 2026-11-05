#!/usr/bin/env python3
"""Test Playwright template availability."""
import os
import time
from e2b import Sandbox


def main():
    print("Creating sandbox with base template...")
    sandbox = Sandbox.create(template="base", timeout=300)
    print(f"Sandbox created: {sandbox.sandbox_id}")
    try:
        time.sleep(10)
        # Check if playwright is installed
        result = sandbox.commands.run('find / -name "playwright*" 2>&1 | head -5')
        print(f"Playwright search: {result.stdout}")
        # Check common locations
        result = sandbox.commands.run('ls /app/ 2>&1 | head -5')
        print(f"/app contents: {result.stdout}")
    except Exception as e:
        print(f"Test failed: {e}")
    finally:
        try:
            sandbox.kill()
            print("Sandbox killed.")
        except:
            pass


if __name__ == "__main__":
    main()
