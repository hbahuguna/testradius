#!/usr/bin/env python3
"""Verify Playwright + Chromium can launch headlessly in an E2B sandbox.

Uses the proven self-hosted E2B workaround:
- Connects via E2B_DOMAIN (nip.io:3002) with HTTP proxy patch (no wildcard DNS/TLS).
- Installs Playwright pip package and Chromium *headless shell* via direct CDN download
  (avoids `playwright install chromium`, which can hang in this environment).
- Installs required Debian apt deps for the headless shell.
- Runs the browser test in the background to avoid ConnectRPC streaming timeouts.

Recommended: run against the `playwright-chromium` template (2CPU/2048MB). The default
`base` template has 512MB and Chromium/V8 may OOM.

Usage:
  export E2B_API_KEY="..." E2B_API_URL="http://8.231.230.69:3000"
  export E2B_DOMAIN="8.231.230.69.nip.io:3002"
  export E2B_PLAYWRIGHT_TEMPLATE="playwright-chromium"   # optional, default below
  python scripts/e2b_playwright_runtime_verify.py
"""
from __future__ import annotations

import os
import time

from e2b import Sandbox
from e2b import connection_config as _e2b_cc
from e2b.sandbox.commands.command_handle import CommandExitException

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

PW_VERSION = os.environ.get("PLAYWRIGHT_VERSION", "1.49.0")
CHROMIUM_REV = os.environ.get("CHROMIUM_REV", "1148")
CDN = "https://playwright.azureedge.net/builds"
BROWSERS_PATH = "/ms-playwright"

DEPS = (
    "libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 "
    "libcups2 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libdrm2 "
    "libxkbcommon0 libasound2 libpango-1.0-0 libcairo2 libglib2.0-0 libx11-6 "
    "libxcb1 libxext6 libxshmfence1 fonts-liberation"
)

INSTALL_HS = f"""set -e
export PLAYWRIGHT_BROWSERS_PATH={BROWSERS_PATH}
sudo mkdir -p "$PLAYWRIGHT_BROWSERS_PATH" 2>/dev/null || mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"
sudo chown "$(id -u):$(id -g)" "$PLAYWRIGHT_BROWSERS_PATH" 2>/dev/null || true
cd /tmp && rm -f hs.zip
wget -q -O hs.zip '{CDN}/chromium/{CHROMIUM_REV}/chromium-headless-shell-linux.zip'
python3 -c "
import zipfile, os, shutil
dest = '{BROWSERS_PATH}/chromium_headless_shell-{CHROMIUM_REV}/chrome-linux'
shutil.rmtree('{BROWSERS_PATH}/chromium_headless_shell-{CHROMIUM_REV}', ignore_errors=True)
os.makedirs(dest, exist_ok=True)
with zipfile.ZipFile('/tmp/hs.zip') as z:
    for info in z.infolist():
        name = info.filename
        if name.startswith('chrome-linux/'): name = name[len('chrome-linux/'):]
        if not name: continue
        target = os.path.join(dest, name)
        if info.is_dir(): os.makedirs(target, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target,'wb') as out: shutil.copyfileobj(src, out)
        perm = (info.external_attr >> 16) & 0o777
        if perm:
            try: os.chmod(target, perm)
            except Exception: pass
print('ok')
"
rm -f /tmp/hs.zip
touch {BROWSERS_PATH}/chromium_headless_shell-{CHROMIUM_REV}/INSTALLATION_COMPLETE
chmod -R a+rX {BROWSERS_PATH} 2>/dev/null || true
test -f {BROWSERS_PATH}/chromium_headless_shell-{CHROMIUM_REV}/chrome-linux/headless_shell
echo DONE
"""

BROWSER_TEST = f"""
import asyncio, os
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', '{BROWSERS_PATH}')
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
        page = await browser.new_page()
        await page.set_content("<html><head><title>Example Domain</title></head><body>ok</body></html>")
        print("TITLE:", await page.title())
        await browser.close()
asyncio.run(main())
"""


def sh(sbx, cmd, timeout=120):
    try:
        r = sbx.commands.run(cmd, timeout=timeout)
        out = ((r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")).strip()
        return out, getattr(r, "exit_code", 0)
    except CommandExitException as e:
        out = ((e.stdout or "") + (("\n" + e.stderr) if e.stderr else "")).strip()
        return out, e.exit_code
    except Exception as e:
        return f"err={e}", -1


def main() -> None:
    domain = os.environ.get("E2B_DOMAIN")
    template = os.environ.get("E2B_PLAYWRIGHT_TEMPLATE", "playwright-chromium")
    kwargs = {"template": template, "timeout": 2400}
    if domain:
        kwargs["domain"] = domain
    print(f"Creating sandbox template={template} ...")
    sbx = Sandbox.create(**kwargs)
    print(f"Sandbox {sbx.sandbox_id}")
    try:
        time.sleep(6)
        print(f"\n== pip install playwright=={PW_VERSION} ==")
        out, ec = sh(sbx, f"python3 -m pip install --no-cache-dir playwright=={PW_VERSION} 2>&1 | tail -3", 600)
        print(out)
        if ec != 0:
            raise SystemExit(f"pip install failed (exit={ec})")

        print("\n== install headless shell ==")
        sbx.files.write("/home/user/install_hs.sh", INSTALL_HS.encode())
        out, ec = sh(sbx, "bash /home/user/install_hs.sh 2>&1", 900)
        print(out[-400:] if out else out)
        if ec != 0 or "DONE" not in (out or ""):
            raise SystemExit(f"headless shell install failed (exit={ec})")

        print("\n== install apt deps ==")
        apt = (
            "sudo bash -lc 'export DEBIAN_FRONTEND=noninteractive; "
            "apt-get update && apt-get install -y --no-install-recommends "
            f"{DEPS} && apt-get clean && rm -rf /var/lib/apt/lists/*' 2>&1 | tail -6"
        )
        out, ec = sh(sbx, apt, 900)
        print(out)
        if ec != 0:
            raise SystemExit(f"apt deps failed (exit={ec})")

        print("\n== browser launch test ==")
        sbx.files.write("/home/user/pw_test.py", BROWSER_TEST.encode())
        sh(
            sbx,
            f"nohup bash -lc 'PLAYWRIGHT_BROWSERS_PATH={BROWSERS_PATH} timeout 120 python3 /home/user/pw_test.py' "
            "> /tmp/pw.out 2>&1 < /dev/null &",
            30,
        )
        final = ""
        for i in range(40):
            time.sleep(3)
            final, _ = sh(sbx, "cat /tmp/pw.out 2>&1; echo __SEP__; pgrep -fa pw_test >/dev/null && echo running || echo done", 30)
            if "TITLE:" in final or final.rstrip().endswith("done"):
                # if done, ensure we got output
                if "TITLE:" in final or "done" in final.split("__SEP__")[-1]:
                    pass
            if "TITLE:" in final:
                break
            if "done" in final.split("__SEP__")[-1] and i > 1:
                break
        final = sh(sbx, "cat /tmp/pw.out 2>&1", 30)[0]
        print(final)
        if "TITLE: Example Domain" in final:
            print("\n✓ Playwright + Chromium launch verification PASSED")
        else:
            raise SystemExit("Browser launch test failed")
    finally:
        try:
            sbx.kill()
        except Exception:
            pass
        print("Sandbox killed.")


if __name__ == "__main__":
    main()
