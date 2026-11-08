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

    def ensure_desktop(self) -> bool:
        """Runtime-bootstrap X stack + browser if template layers are missing.

        Uses background+poll for long installs to avoid E2B request timeouts.
        """
        if self._ensured:
            return True
        try:
            browser_probe = "(command -v google-chrome >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1 || ls /ms-playwright/chromium-*/chrome-linux/chrome /home/user/.cache/ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null | head -1 | grep -q chrome)"
            chk = self._run(f"which Xvfb xdotool scrot >/dev/null 2>&1 && {browser_probe} && echo HAS_ALL || echo MISSING", timeout=60)
            if "HAS_ALL" in (chk.get("stdout") or ""):
                self._start_display()
                self._ensured = True
                return True

            # 1) X stack (fast, ~60s)
            xchk = self._run("which Xvfb xdotool scrot >/dev/null 2>&1 && echo HAS_X || echo MISSING_X", timeout=60)
            if "HAS_X" not in (xchk.get("stdout") or ""):
                self._ensure_log.append("runtime-bootstrap: installing X stack + Chromium deps")
                deps = (
                    "xvfb openbox xterm xdotool scrot wmctrl x11-utils fonts-liberation "
                    "libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 "
                    "libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 "
                    "libgbm1 libpango-1.0-0 libcairo2 libasound2t64 libatspi2.0-0t64 "
                    "libglib2.0-0t64 libdbus-1-3 libexpat1 libx11-6 libxcb1 libxext6"
                )
                if not self._run_bg_poll(
                    "apt-x",
                    f"sudo apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends {deps} && sudo apt-get clean",
                    "/tmp/apt-x.log", "APT_X_DONE", poll_timeout=900,
                ):
                    return False

            # 2) Browser (slow, ~3-5 min for 161MB download)
            bchk = self._run(f"{browser_probe} && echo HAS_BROWSER || echo MISSING_BROWSER", timeout=60)
            if "HAS_BROWSER" not in (bchk.get("stdout") or ""):
                self._ensure_log.append("runtime-bootstrap: installing Playwright Chromium")
                if not self._run_bg_poll(
                    "playwright-chromium",
                    "python3 -m pip install -q playwright==1.49.0 pillow requests && mkdir -p /home/user/.cache/ms-playwright && PLAYWRIGHT_BROWSERS_PATH=/home/user/.cache/ms-playwright python3 -m playwright install chromium",
                    "/tmp/pw-install.log", "PW_INSTALL_DONE", poll_timeout=900, poll_interval=10,
                ):
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
    # Fallback: scrot + base64 (files.read text-decodes binary and corrupts PNGs
        # with U+FFFD EF BF BD — Preview then reports "damaged"). Use run_command stdout.
        import base64

        tmp = "/tmp/harness-shot.png"
        res = self._run(f"DISPLAY={self.display} scrot {shlex.quote(tmp)}; echo scrot:$?", timeout=60)
        try:
            b64res = self._run(f"base64 -w0 {shlex.quote(tmp)}", timeout=60)
            b64 = (b64res.get("stdout") or "").strip()
            if b64:
                return base64.b64decode(b64)
        except Exception as e:
            self._ensure_log.append(f"screenshot base64 failed: {e}")
        self._ensure_log.append(f"screenshot scrot exit={res.get('exit_code')} stderr={str(res.get('stderr',''))[:300]}")
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
        # Ensure window manager is running (needed for Chrome to map/render on Xvfb).
        self._run(f"pgrep -f 'openbox' >/dev/null 2>&1 || (nohup openbox >/tmp/openbox.log 2>&1 & sleep 1)", timeout=30)
        q = shlex.quote(url)
        chrome_bin = (
            "CHROME=$(command -v google-chrome || command -v chromium || "
            "ls /ms-playwright/chromium-*/chrome-linux/chrome /home/user/.cache/ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null | head -1)"
        )
        flags = (
            "--no-sandbox --disable-setuid-sandbox --disable-dev-shm-usage --disable-gpu "
            "--no-first-run --no-default-browser-check --disable-background-networking "
            "--disable-sync --disable-translate --disable-features=VizDisplayCompositor "
            "--no-zygote --disable-software-rasterizer "
            "--user-data-dir=/tmp/chrome-profile --window-size=1440,900 --window-position=0,0"
        )
        res = self._run(
            f'DISPLAY={self.display} {chrome_bin}; if [ -z "$CHROME" ]; then echo NO_BROWSER; exit 127; fi; '
            f'rm -f /tmp/harness-browser.log; nohup "$CHROME" {flags} {q} >/tmp/harness-browser.log 2>&1 & sleep 10; '
            f'if pgrep -f chrome-linux/chrome >/dev/null 2>&1; then echo navigated:$CHROME; else echo CHROME_DIED; tail -40 /tmp/harness-browser.log 2>&1; exit 1; fi',
            timeout=90,
        )
        return res.get("exit_code", 0) == 0 and "NO_BROWSER" not in (res.get("stdout") or "")
