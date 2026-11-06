#!/usr/bin/env python3
"""Build a Playwright+Chromium template on self-hosted E2B Embed using MANUAL browser install.

Avoids `playwright install chromium` which can hang in E2B Embed template builds.
Installs headless shell (and chromium) via direct download + correct cache layout.

Usage:
  export E2B_API_KEY="..." E2B_API_URL="http://8.231.230.69:3000"
  export E2B_PLAYWRIGHT_TEMPLATE="playwright-chromium"
  python scripts/build_e2b_playwright_template_manual.py
"""
from __future__ import annotations

import os

from e2b import Template


def on_log(e):
    try:
        print(str(e), flush=True)
    except Exception:
        print(e, flush=True)


# Playwright 1.49.0 / chromium build 1148 (as observed). Adjust if changing PW version.
PW_VERSION = os.environ.get("PLAYWRIGHT_VERSION", "1.49.0")
CHROMIUM_REV = os.environ.get("CHROMIUM_REV", "1148")
CDN = "https://playwright.azureedge.net/builds"

INSTALL_BROWSERS = f"""set -e
export PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
sudo mkdir -p "$PLAYWRIGHT_BROWSERS_PATH" 2>/dev/null || mkdir -p "$PLAYWRIGHT_BROWSERS_PATH"
sudo chown "$(id -u):$(id -g)" "$PLAYWRIGHT_BROWSERS_PATH" 2>/dev/null || true
# free space from apt caches if present
sudo apt-get clean 2>/dev/null || true
sudo rm -rf /var/lib/apt/lists/* /var/cache/apt/* /tmp/* 2>/dev/null || true
df -h / /tmp "$PLAYWRIGHT_BROWSERS_PATH" 2>&1 | head -6 || true
cd /tmp
wget -q -O hs.zip '{CDN}/chromium/{CHROMIUM_REV}/chromium-headless-shell-linux.zip'
python3 -c "
import zipfile, os, shutil
dest = '$PLAYWRIGHT_BROWSERS_PATH/chromium_headless_shell-{CHROMIUM_REV}/chrome-linux'
if os.path.exists('$PLAYWRIGHT_BROWSERS_PATH/chromium_headless_shell-{CHROMIUM_REV}'): shutil.rmtree('$PLAYWRIGHT_BROWSERS_PATH/chromium_headless_shell-{CHROMIUM_REV}')
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
            except: pass
print('extracted')
"
rm -f /tmp/hs.zip
touch "$PLAYWRIGHT_BROWSERS_PATH/chromium_headless_shell-{CHROMIUM_REV}/INSTALLATION_COMPLETE"
chmod -R a+rX "$PLAYWRIGHT_BROWSERS_PATH" 2>/dev/null || sudo chmod -R a+rX "$PLAYWRIGHT_BROWSERS_PATH" || true
ls "$PLAYWRIGHT_BROWSERS_PATH"
echo DONE
"""


def main() -> None:
    api_key = os.environ["E2B_API_KEY"]
    api_url = os.environ.get("E2B_API_URL", "http://8.231.230.69:3000")
    alias = os.environ.get("E2B_PLAYWRIGHT_TEMPLATE", "playwright-chromium")

    tpl = (
        Template()
        .from_python_image("3.11")
        .set_envs({"DEBIAN_FRONTEND": "noninteractive", "PLAYWRIGHT_BROWSERS_PATH": "/ms-playwright"})
        .apt_install([
            "ca-certificates", "wget", "unzip", "fonts-liberation",
            "libnss3", "libnspr4", "libdbus-1-3", "libatk1.0-0", "libatk-bridge2.0-0",
            "libatspi2.0-0", "libcups2", "libxcomposite1", "libxdamage1", "libxfixes3",
            "libxrandr2", "libgbm1", "libdrm2", "libxkbcommon0", "libasound2",
            "libpango-1.0-0", "libcairo2", "libglib2.0-0", "libx11-6", "libxcb1",
            "libxext6", "libxshmfence1",
        ])
        .pip_install([f"playwright=={PW_VERSION}"])
        .run_cmd(INSTALL_BROWSERS)
        .run_cmd("python3 -c \"import playwright; print(playwright.__name__)\"")
        .set_workdir("/home/user")
    )

    print(f"Building template alias={alias} (manual browser install, 2CPU/2048MB) via {api_url}...")
    info = Template.build(
        tpl,
        alias=alias,
        cpu_count=2,
        memory_mb=2048,
        on_build_logs=on_log,
        api_key=api_key,
        api_url=api_url,
    )
    print(f"\nBuild finished: {info}")


if __name__ == "__main__":
    main()
