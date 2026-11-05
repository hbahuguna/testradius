#!/usr/bin/env python3
"""Hello world test for E2B sandbox."""
import os
from e2b import Sandbox


def main():
    print("Creating sandbox...")
    sandbox = Sandbox.create()
    print(f"Sandbox created: {sandbox.sandbox_id}")
    result = sandbox.commands.run('echo "Hello from the Manual QA Harness!"')
    print(f"Command output: {result.stdout}")
    sandbox.kill()
    print("Sandbox killed.")


if __name__ == "__main__":
    main()
