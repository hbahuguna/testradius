"""Runtime bootstrap utilities for Playwright in self-hosted E2B sandboxes."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...sandbox.base import BaseSandboxProvider

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

INSTALL_HS_SCRIPT = f"""set -e
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


def is_playwright_ready(provider: BaseSandboxProvider, sandbox_id: str, chromium_rev: str = CHROMIUM_REV) -> bool:
    """Check if Playwright python package and chromium headless shell are installed in sandbox."""
    check_cmd = (
        f"python3 -c 'import playwright' 2>/dev/null && "
        f"test -f {BROWSERS_PATH}/chromium_headless_shell-{chromium_rev}/chrome-linux/headless_shell && "
        "echo READY"
    )
    res = provider.run_command(sandbox_id, check_cmd, timeout=15)
    return "READY" in (res.get("stdout") or "")


def ensure_playwright_ready(
    provider: BaseSandboxProvider,
    sandbox_id: str,
    pw_version: str = PW_VERSION,
    chromium_rev: str = CHROMIUM_REV,
    timeout: int = 900,
) -> bool:
    """Ensure Playwright and Chromium are installed in the sandbox.

    If not already ready, runs the proven runtime bootstrap:
    1. pip install playwright
    2. direct download & extract headless shell
    3. apt-get install required system libraries
    """
    if is_playwright_ready(provider, sandbox_id, chromium_rev):
        return True

    # 1. pip install playwright
    res_pip = provider.run_command(
        sandbox_id,
        f"python3 -m pip install --no-cache-dir playwright=={pw_version} >/tmp/pip.log 2>&1",
        timeout=300,
    )
    if res_pip.get("exit_code") != 0:
        tail = provider.run_command(sandbox_id, "tail -n 10 /tmp/pip.log", timeout=15)
        raise RuntimeError(f"Failed to install Playwright pip package: {tail.get('stdout') or res_pip}")

    # 2. install headless shell
    provider.upload_file(sandbox_id, "/home/user/install_hs.sh", INSTALL_HS_SCRIPT.encode("utf-8"))
    res_hs = provider.run_command(sandbox_id, "bash /home/user/install_hs.sh 2>&1", timeout=300)
    if res_hs.get("exit_code") != 0 or "DONE" not in (res_hs.get("stdout") or ""):
        raise RuntimeError(f"Failed to install Chromium headless shell: {res_hs.get('stdout') or res_hs.get('stderr')}")

    # 3. install apt deps
    apt_cmd = (
        "sudo bash -lc 'export DEBIAN_FRONTEND=noninteractive; "
        f"apt-get update && apt-get install -y --no-install-recommends {DEPS} "
        "&& apt-get clean && rm -rf /var/lib/apt/lists/*' >/tmp/apt.log 2>&1"
    )
    res_apt = provider.run_command(sandbox_id, apt_cmd, timeout=600)
    if res_apt.get("exit_code") != 0:
        tail = provider.run_command(sandbox_id, "tail -n 10 /tmp/apt.log", timeout=15)
        raise RuntimeError(f"Failed to install apt dependencies: {tail.get('stdout') or res_apt}")

    return is_playwright_ready(provider, sandbox_id, chromium_rev)
