"""Desktop primitives for computer-use spike (screenshot / mouse / keyboard / wait).

Design follows <https://github.com/e2b-dev/open-computer-use> (``SandboxAgent`` uses
``sandbox.screenshot()``, ``move_mouse``, ``left_click``, ``write``/``press`` via the
``e2b-desktop`` SDK). We *wrap* that surface behind a small harness protocol so the spike
is testable with mocks and does not hard-depend on ``e2b-desktop`` until live.

Reuse/wrap decision (see docs/E2B_GEMINI_COMPUTER_USE_SPIKE.md):
- Do **not** fork open-computer-use. Wrap its sandbox-action surface.
- Gemini is a first-class provider in open-computer-use (Gemini 2.0 Flash via
  OpenAI-compat endpoint); harness proposes actions and validates them (008.5).
"""
from __future__ import annotations

import os
import shlex
import time
from typing import Any, Dict, Optional, Protocol


class ComputerUsePrimitives(Protocol):
    def screenshot(self) -> bytes: ...
    def move_mouse(self, x: int, y: int) -> bool: ...
    def click(self, x: int, y: int, *, button: str = "left", double: bool = False) -> bool: ...
    def type_text(self, text: str) -> bool: ...
    def press_key(self, key: str) -> bool: ...
    def scroll(self, *, delta_x: int = 0, delta_y: int = 0) -> bool: ...
    def wait(self, seconds: float) -> bool: ...
    def navigate(self, url: str) -> bool: ...


class MockComputerUsePrimitives:
    """Safe in-memory primitives for tests/demos. Records actions and screenshots."""

    def __init__(self, *, width: int = 1440, height: int = 900):
        self.width = width
        self.height = height
        self.actions: list[Dict[str, Any]] = []
        self.current_url: Optional[str] = None
        self._shots = 0
        self._screenshot_bytes = b"\x89PNG\r\n\x1a\nmock-screenshot"

    def _record(self, action: str, **kwargs: Any) -> None:
        self.actions.append({"action": action, **kwargs})

    def screenshot(self) -> bytes:
        self._shots += 1
        self._record("screenshot", index=self._shots)
        # Minimal valid PNG header bytes for artifact writing; unique per shot.
        return self._screenshot_bytes + f":{self._shots}".encode()

    def move_mouse(self, x: int, y: int) -> bool:
        self._record("move_mouse", x=x, y=y)
        return True

    def click(self, x: int, y: int, *, button: str = "left", double: bool = False) -> bool:
        self._record("click", x=x, y=y, button=button, double=double)
        return True

    def type_text(self, text: str) -> bool:
        self._record("type_text", text=text)
        return True

    def press_key(self, key: str) -> bool:
        self._record("press_key", key=key)
        return True

    def scroll(self, *, delta_x: int = 0, delta_y: int = 0) -> bool:
        self._record("scroll", delta_x=delta_x, delta_y=delta_y)
        return True

    def wait(self, seconds: float) -> bool:
        self._record("wait", seconds=seconds)
        time.sleep(0)  # demo-safe, no delay
        return True

    def navigate(self, url: str) -> bool:
        self.current_url = url
        self._record("navigate", url=url)
        return True


class E2BDesktopPrimitives:
    """Live E2B desktop primitives (env-dependent).

    Prefers the ``e2b-desktop`` SDK surface (``screenshot``, ``move_mouse``,
    ``left_click``, ...) per open-computer-use; falls back to ``xdotool``/``scrot``
    shell commands via the sandbox provider when that SDK is unavailable.
    """

    def __init__(self, *, provider: Any, sandbox_id: str, display: str = ":99", width: int = 1440, height: int = 900):
        self.provider = provider
        self.sandbox_id = sandbox_id
        self.display = display
        self.width = width
        self.height = height
        self._sbx: Any | None = None
        self._ensured = False
        self._ensure_log: list[str] = []

    def _sdk_sandbox(self) -> Any | None:
        if self._sbx is not None:
            return self._sbx
        try:
            from e2b import Sandbox as _Sandbox  # type: ignore

            kw: Dict[str, Any] = {}
            if getattr(self.provider, "api_key", None):
                kw["api_key"] = self.provider.api_key
            if getattr(self.provider, "domain", None):
                kw["domain"] = self.provider.domain
            if getattr(self.provider, "api_url", None):
                kw["api_url"] = self.provider.api_url
            self._sbx = _Sandbox.connect(self.sandbox_id, **kw)
            return self._sbx
        except Exception:
            return None

    def _run(self, command: str, timeout: int = 60) -> Dict[str, Any]:
        return self.provider.run_command(self.sandbox_id, command, timeout=timeout)

    def _start_display(self) -> None:
        # Simple, separate commands (avoid fragile compound chains that can yield exit=-1).
        self._run("pkill -f 'Xvfb :99' >/dev/null 2>&1 || true", timeout=30)
        self._run("rm -f /tmp/.X99-lock /tmp/.X11-unix/X99", timeout=30)
        self._run(
            f"nohup Xvfb {self.display} -screen 0 {self.width}x{self.height}x24 +extension RANDR >/tmp/xvfb.log 2>&1 &",
            timeout=30,
        )
        self._run("sleep 2", timeout=10)
        self._run("pgrep -f openbox >/dev/null 2>&1 || nohup openbox >/tmp/openbox.log 2>&1 &", timeout=30)
        self._run("sleep 1", timeout=10)

    def _find_chrome(self) -> str:
        """Return path to a *working* Chrome/Chromium, or empty string.

        Validates with `--version` (catches SIGBUS from incompatible builds, e.g.
        Playwright's ubuntu20.04 fallback on Debian 13).
        """
        cmd = (
            "for c in /dev/shm/cft/chrome-linux64/chrome /dev/shm/cft/*/chrome "
            "$(ls /ms-playwright/chromium-*/chrome-linux/chrome /home/user/.cache/ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null) "
            "$(command -v google-chrome-stable google-chrome chromium 2>/dev/null); do "
            '[ -x "$c" ] || continue; timeout 5 "$c" --version >/dev/null 2>&1 && echo "OK:$c" && exit 0; '
            "done; echo NONE"
        )
        res = self._run(cmd, timeout=60)
        out = (res.get("stdout") or "").strip()
        for line in out.splitlines():
            if line.startswith("OK:"):
                return line[3:].strip()
        return ""

    def _run_bg_poll(self, label: str, cmd: str, log_path: str, done_marker: str, *, poll_timeout: int = 900, poll_interval: int = 5) -> bool:
        """Run long command in background and poll (avoids E2B request timeout)."""
        import time as _time

        self._run(f"rm -f {shlex.quote(log_path)}; nohup bash -c {shlex.quote(cmd + f' && echo {done_marker} || echo {done_marker}_FAIL')} >{shlex.quote(log_path)} 2>&1 & echo bg_started", timeout=60)
        deadline = _time.time() + poll_timeout
        while _time.time() < deadline:
            res = self._run(f"tail -5 {shlex.quote(log_path)} 2>/dev/null; echo POLL_END", timeout=60)
            out = res.get("stdout") or ""
            if done_marker in out:
                ok = f"{done_marker}_FAIL" not in out
                if not ok:
                    self._ensure_log.append(f"{label} failed: {out[-500:]}")
                return ok
            _time.sleep(poll_interval)
        self._ensure_log.append(f"{label} timed out after {poll_timeout}s")
        return False

    def _install_cft_browser(self) -> str:
        """Install Chrome for Testing to /dev/shm (tmpfs) to avoid root-disk limits."""
        self._ensure_log.append("runtime-bootstrap: installing Chrome for Testing to /dev/shm")
        install = (
            "set -e; "
            "URL=$(curl -fsSL 'https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json' | "
            "python3 -c \"import json,sys; d=json.load(sys.stdin); print([x['url'] for x in d['channels']['Stable']['downloads']['chrome'] if x['platform']=='linux64'][0])\"); "
            "curl -fSL \"$URL\" -o /dev/shm/chrome.zip; "
            "rm -rf /dev/shm/cft && mkdir -p /dev/shm/cft; "
            "unzip -q /dev/shm/chrome.zip -d /dev/shm/cft; rm -f /dev/shm/chrome.zip; "
            "find /dev/shm/cft -name chrome -type f | head -1"
        )
        ok = self._run_bg_poll("cft-install", install, "/tmp/cft-install.log", "CFT_DONE", poll_timeout=900, poll_interval=10)
        if not ok:
            return ""
        return self._find_chrome()

    def ensure_desktop(self) -> bool:
        """Runtime-bootstrap X stack + a *working* browser if template layers are missing.

        Uses background+poll for long installs to avoid E2B request timeouts.
        Prefers Chrome for Testing on /dev/shm (tmpfs) because Playwright's
        ubuntu20.04 Chromium fallback can SIGBUS on Debian 13 sandboxes.
        """
        if self._ensured:
            return True
        try:
            x_ok = "HAS_X" in (self._run("which Xvfb xdotool scrot >/dev/null 2>&1 && echo HAS_X || echo MISSING_X", timeout=60).get("stdout") or "")
            chrome = self._find_chrome() if x_ok else ""
            if x_ok and chrome:
                self._start_display()
                self._ensured = True
                return True

            # 1) X stack + deps (incl. curl/unzip for CfT, Chromium runtime libs)
            if not x_ok:
                self._ensure_log.append("runtime-bootstrap: installing X stack + Chromium deps")
                deps = (
                    "xvfb openbox xterm xdotool scrot wmctrl x11-utils fonts-liberation "
                    "curl unzip ca-certificates "
                    "libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 "
                    "libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 "
                    "libgbm1 libpango-1.0-0 libcairo2 libasound2t64 libatspi2.0-0t64 "
                    "libglib2.0-0t64 libdbus-1-3 libexpat1 libx11-6 libxcb1 libxext6"
                )
                if not self._run_bg_poll(
                    "apt-x",
                    f"sudo apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends {deps} && sudo apt-get clean && sudo rm -rf /var/lib/apt/lists/* /var/cache/apt/* || true",
                    "/tmp/apt-x.log", "APT_X_DONE", poll_timeout=900,
                ):
                    return False

            # 2) Working browser (Chrome for Testing on tmpfs; avoids root disk + SIGBUS)
            chrome = self._find_chrome()
            if not chrome:
                chrome = self._install_cft_browser()
            if not chrome:
                self._ensure_log.append("no working browser found after bootstrap")
                return False

            self._start_display()
            self._ensured = True
            return True
        except Exception as e:
            self._ensure_log.append(f"ensure_desktop error: {e}")
            return False

    def screenshot(self) -> bytes:
        self.ensure_desktop()
        sbx = self._sdk_sandbox()
        if sbx is not None and hasattr(sbx, "screenshot"):
            try:
                data = sbx.screenshot()  # e2b-desktop API: bytes or (sandbox) path
                if isinstance(data, bytes):
                    return data
                if isinstance(data, str):
                    if os.path.exists(data):
                        return open(data, "rb").read()
                    # Path inside sandbox: fetch via provider
                    try:
                        fetched = self.provider.download_file(self.sandbox_id, data)
                        if fetched:
                            return fetched if isinstance(fetched, bytes) else str(fetched).encode()
                    except Exception:
                        pass
                    return data.encode()
                if data:
                    return bytes(data)  # type: ignore[arg-type]
            except Exception:
                pass
        # Fallback: scrot + base64 via run_command stdout (files.read text-decodes binary
        # and corrupts PNGs). Retry: Xvfb/root capture can intermittently return a blank
        # desktop (~3-4KB PNG, 1440x900) even when Chrome is rendered; settle and retry.
        import base64
        import time as _time

        tmp = "/tmp/harness-shot.png"
        best = b""
        for attempt in range(4):
            self._run(
                f"DISPLAY={self.display} scrot -o {shlex.quote(tmp)} 2>/dev/null || DISPLAY={self.display} scrot {shlex.quote(tmp)}",
                timeout=60,
            )
            try:
                b64res = self._run(f"base64 -w0 {shlex.quote(tmp)} 2>/dev/null", timeout=60)
                b64 = (b64res.get("stdout") or "").strip()
                if b64:
                    decoded = base64.b64decode(b64, validate=False)
                    if len(decoded) > len(best):
                        best = decoded
                    # Real 1440x900 rendered content is >> 15KB; blank desktop is ~3-4KB.
                    if len(decoded) > 15000:
                        return decoded
            except Exception as e:
                self._ensure_log.append(f"screenshot decode failed: {e}")
            if attempt < 3:
                _time.sleep(2)
        if best:
            self._ensure_log.append(f"screenshot: only blank/small capture ({len(best)} bytes) after retries")
            return best
        return b""

    def move_mouse(self, x: int, y: int) -> bool:
        sbx = self._sdk_sandbox()
        if sbx is not None and hasattr(sbx, "move_mouse"):
            try:
                sbx.move_mouse(int(x), int(y))
                return True
            except Exception:
                pass
        res = self._run(f"DISPLAY={self.display} xdotool mousemove {int(x)} {int(y)}")
        return res.get("exit_code", 0) == 0

    def click(self, x: int, y: int, *, button: str = "left", double: bool = False) -> bool:
        self.move_mouse(x, y)
        sbx = self._sdk_sandbox()
        if sbx is not None:
            try:
                if double and hasattr(sbx, "double_click"):
                    sbx.double_click()
                    return True
                if hasattr(sbx, "left_click") and button == "left":
                    sbx.left_click()
                    return True
                if hasattr(sbx, "right_click") and button == "right":
                    sbx.right_click()
                    return True
            except Exception:
                pass
        btn = {"left": "1", "right": "3", "middle": "2"}.get(button, "1")
        cmd = f"DISPLAY={self.display} xdotool click {'--repeat 2 --delay 50 ' if double else ''}{btn}"
        res = self._run(cmd)
        return res.get("exit_code", 0) == 0

    def type_text(self, text: str) -> bool:
        sbx = self._sdk_sandbox()
        if sbx is not None and hasattr(sbx, "write"):
            try:
                sbx.write(text, chunk_size=50, delay_in_ms=12)
                return True
            except Exception:
                pass
        res = self._run(f"DISPLAY={self.display} xdotool type {shlex.quote(text)}")
        return res.get("exit_code", 0) == 0

    def press_key(self, key: str) -> bool:
        sbx = self._sdk_sandbox()
        if sbx is not None and hasattr(sbx, "press"):
            try:
                sbx.press(key)
                return True
            except Exception:
                pass
        res = self._run(f"DISPLAY={self.display} xdotool key {shlex.quote(key)}")
        return res.get("exit_code", 0) == 0

    def scroll(self, *, delta_x: int = 0, delta_y: int = 0) -> bool:
        sbx = self._sdk_sandbox()
        if sbx is not None and hasattr(sbx, "scroll"):
            try:
                sbx.scroll(dx=int(delta_x), dy=int(delta_y))
                return True
            except Exception:
                pass
        # xdotool scroll is via button clicks (4=up, 5=down) on hovered widget.
        btn = "5" if delta_y < 0 else "4"
        clicks = max(1, abs(delta_y) // 60)
        res = self._run(f"DISPLAY={self.display} xdotool click --repeat {clicks} --delay 30 {btn}")
        return res.get("exit_code", 0) == 0

    def wait(self, seconds: float) -> bool:
        res = self._run(f"sleep {max(0, float(seconds))}")
        return res.get("exit_code", 0) == 0

    def navigate(self, url: str) -> bool:
        # Desktop: open in browser on the virtual display.
        if not self.ensure_desktop():
            return False
        self._run("pgrep -f openbox >/dev/null 2>&1 || (nohup openbox >/tmp/openbox.log 2>&1 & sleep 1)", timeout=30)
        chrome = self._find_chrome()
        if not chrome:
            self._ensure_log.append("navigate: no working browser")
            return False
        q = shlex.quote(url)
        cq = shlex.quote(chrome)
        flags = (
            "--no-sandbox --disable-setuid-sandbox --disable-dev-shm-usage --disable-gpu "
            "--no-first-run --no-default-browser-check --disable-background-networking "
            "--disable-sync --disable-translate "
            "--user-data-dir=/dev/shm/chrome-profile --window-size=1440,900 --window-position=0,0"
        )
        # export DISPLAY so Chrome (and child processes) inherit it; prefix-only would
        # apply to `rm`, not `nohup chrome`.
        res = self._run(
            f'export DISPLAY={self.display}; rm -f /tmp/harness-browser.log; '
            f'nohup {cq} {flags} {q} >/tmp/harness-browser.log 2>&1 & sleep 12; '
            f'if pgrep -fa chrome | grep -q "chrome"; then echo navigated:{chrome}; '
            f'else echo CHROME_DIED; tail -60 /tmp/harness-browser.log 2>&1; exit 1; fi',
            timeout=90,
        )
        return res.get("exit_code", 0) == 0 and "CHROME_DIED" not in (res.get("stdout") or "")
