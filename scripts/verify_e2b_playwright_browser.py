#!/usr/bin/env python3
"""Verify Playwright can launch Chromium in an E2B template.

Usage:
  export E2B_API_KEY="..."
  export E2B_API_URL="http://8.231.230.69:3000"
  export E2B_DOMAIN="8.231.230.69.nip.io:3002"   # self-hosted proxy
  export E2B_PLAYWRIGHT_TEMPLATE="playwright-chromium"
  python scripts/verify_e2b_playwright_browser.py
"""
from __future__ import annotations

import os
import time

from e2b import Sandbox
from e2b import connection_config as _e2b_cc

# HTTP patch for self-hosted proxy with domain:port
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


SCRIPT = r'''
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()
        await page.goto("https://example.com", wait_until="domcontentloaded", timeout=60000)
        title = await page.title()
        print("TITLE:", title)
        await browser.close()

asyncio.run(main())
'''


def main() -> None:
    template = os.environ.get("E2B_PLAYWRIGHT_TEMPLATE", "playwright-chromium")
    domain = os.environ.get("E2B_DOMAIN")
    kwargs = {"template": template, "timeout": 600}
    if domain:
        kwargs["domain"] = domain

    print(f"Creating sandbox template={template} domain={domain}...")
    sbx = Sandbox.create(**kwargs)
    print(f"Sandbox: {sbx.sandbox_id}")
    try:
        time.sleep(8)
        sbx.files.write("/home/user/pw_test.py", SCRIPT.encode())
        r = sbx.commands.run("python3 /home/user/pw_test.py", timeout=180)
        out = (r.stdout or "") + (r.stderr or "")
        print(out)
        if "Example Domain" not in out and "TITLE:" not in out:
            raise SystemExit("Browser verification did not produce expected title")
        print("✓ Playwright + Chromium launch verified")
    finally:
        sbx.kill()
        print("Sandbox killed.")


if __name__ == "__main__":
    main()
