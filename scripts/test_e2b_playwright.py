#!/usr/bin/env python3
"""Test Playwright template availability on E2B instance."""
import os
from e2b import Sandbox
import requests


def main():
    api_key = os.environ.get("E2B_API_KEY")
    api_url = os.environ.get("E2B_API_URL", "http://8.231.230.69:3000")
    
    # Check available templates
    print("Checking available templates...")
    try:
        r = requests.get(f"{api_url}/templates", headers={"X-API-Key": api_key})
        templates = r.json() if r.ok else []
        names = []
        for t in templates:
            names.extend(t.get("names", []) or [])
            names.extend(t.get("aliases", []) or [])
        print(f"Available templates: {names}")
        has_playwright = any("playwright" in n.lower() for n in names)
        if has_playwright:
            print("✓ Playwright template found")
        else:
            print("✗ Playwright template not found (base template available)")
    except Exception as e:
        print(f"Template check failed: {e}")
    
    # Try to create with base template
    print("\nCreating sandbox with base template...")
    try:
        sandbox = Sandbox.create(template="base", timeout=300)
        print(f"✓ Sandbox created: {sandbox.sandbox_id}")
        sandbox.kill()
        print("✓ Sandbox killed")
    except Exception as e:
        print(f"✗ Sandbox creation failed: {e}")


if __name__ == "__main__":
    main()
