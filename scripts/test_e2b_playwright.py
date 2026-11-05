#!/usr/bin/env python3
"""Test Playwright/template availability on E2B instance.

Self-hosted: set E2B_API_KEY, E2B_API_URL, E2B_DOMAIN=<domain>:3002
"""
import os
import time

import requests
from e2b import Sandbox
from e2b import connection_config as _e2b_cc

if not getattr(_e2b_cc, "_tr_http_patched", False):
    _orig_host = _e2b_cc.ConnectionConfig.get_host

    def _http_url(self, sandbox_id, sandbox_domain, port=None):
        port = self.envd_port if port is None else port
        if self._sandbox_url:
            return self._sandbox_url
        return f"http://{_orig_host(self, sandbox_id, sandbox_domain, port)}"

    _e2b_cc.ConnectionConfig.get_sandbox_url = _http_url
    _e2b_cc.ConnectionConfig.get_sandbox_direct_url = _http_url
    _e2b_cc._tr_http_patched = True


def main():
    api_key = os.environ.get("E2B_API_KEY")
    api_url = os.environ.get("E2B_API_URL", "http://8.231.230.69:3000")
    domain = os.environ.get("E2B_DOMAIN")

    print("Checking available templates...")
    names = []
    try:
        r = requests.get(f"{api_url}/templates", headers={"X-API-Key": api_key}, timeout=15)
        templates = r.json() if r.ok else []
        for t in templates:
            names.extend(t.get("names", []) or [])
            names.extend(t.get("aliases", []) or [])
        print(f"Available templates: {sorted(set(names))}")
        if any("playwright" in n.lower() for n in names):
            print("✓ Playwright template found")
        else:
            print("⚠ Playwright template not found (use base + custom template build)")
    except Exception as e:
        print(f"Template check failed: {e}")

    probe_template = os.environ.get("E2B_PROBE_TEMPLATE") or (
        "playwright-chromium" if any("playwright-chromium" in n for n in names) else "base"
    )
    print(f"\nProbing template '{probe_template}' for Playwright/Chromium...")
    kwargs = {"template": probe_template, "timeout": 300}
    if domain:
        kwargs["domain"] = domain
    sandbox = Sandbox.create(**kwargs)
    print(f"✓ Sandbox created: {sandbox.sandbox_id}")
    try:
        time.sleep(8)
        checks = [
            ("python", "python3 --version; which python3"),
            ("playwright import", "python3 -c \"import playwright,sys; print(playwright.__version__, sys.executable)\" 2>&1 | tail -2"),
            ("playwright CLI", "python3 -m playwright --version 2>&1 | tail -2"),
            ("browsers", "ls /ms-playwright 2>&1 | head -5 || echo none"),
        ]
        for label, cmd in checks:
            r = sandbox.commands.run(cmd, timeout=30)
            out = ((r.stdout or "") + (r.stderr or "")).strip() or "(none)"
            print(f"  {label}: {out}")
    finally:
        sandbox.kill()
        print("✓ Sandbox killed")


if __name__ == "__main__":
    main()
