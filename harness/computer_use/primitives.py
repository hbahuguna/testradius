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

    def ensure_desktop(self) -> bool:
        """Runtime-bootstrap X stack if the sandbox was created without it.

        Template layers can be stripped by self-hosted finalization; runtime
        install is the proven Playwright-pattern fallback (live, no mock).
        """
        if self._ensured:
            return True
        try:
            chk = self._run("which Xvfb xdotool scrot >/dev/null 2>&1 && echo HAS_TOOLS || echo MISSING", timeout=60)
            if "HAS_TOOLS" in (chk.get("stdout") or ""):
                self._run(f"rm -f /tmp/.X99-lock /tmp/.X11-unix/X99; nohup Xvfb {self.display} -screen 0 {self.width}x{self.height}x24 +extension RANDR >/tmp/xvfb.log 2>&1 & sleep 2", timeout=60)
                self._ensured = True
                return True
            self._ensure_log.append("runtime-bootstrap: installing xvfb/openbox/xterm/xdotool/scrot")
            res = self._run("sudo apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends xvfb openbox xterm xdotool scrot fonts-liberation && sudo apt-get clean", timeout=600)
            if res.get("exit_code", 0) != 0:
                self._ensure_log.append(f"bootstrap failed: {str(res.get('stderr',''))[:500]}")
                return False
            self._run(f"rm -f /tmp/.X99-lock /tmp/.X11-unix/X99; nohup Xvfb {self.display} -screen 0 {self.width}x{self.height}x24 +extension RANDR >/tmp/xvfb.log 2>&1 & sleep 2", timeout=60)
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
                data = sbx.screenshot()  # e2b-desktop API: bytes or path
                if isinstance(data, (str, bytes)) and isinstance(data, bytes):
                    return data
                if isinstance(data, str) and os.path.exists(data):
                    return open(data, "rb").read()
                if data:
                    return bytes(data)  # type: ignore[arg-type]
            except Exception:
                pass
    # Fallback: scrot on DISPLAY (surface errors instead of silent 0-byte PNGs).
        tmp = "/tmp/harness-shot.png"
        res = self._run(f"DISPLAY={self.display} scrot {shlex.quote(tmp)}", timeout=60)
        if res.get("exit_code", 0) != 0:
            res2 = self._run(f"DISPLAY={self.display} import -window root {shlex.quote(tmp)} 2>/dev/null; echo import:$?", timeout=60)
            self._ensure_log.append(f"screenshot scrot failed: {str(res.get('stderr',''))[:300]}")
        try:
            data = self.provider.download_file(self.sandbox_id, tmp)
        except Exception as e:
            self._ensure_log.append(f"screenshot download failed: {e}")
            return b""
        if not data:
            self._ensure_log.append(f"screenshot empty (scrot exit={res.get('exit_code')}) ensure_log={self._ensure_log}")
        return data

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
        # Desktop: open in default browser on the virtual display.
        # Desktop template ships Playwright Chromium (no Debian chromium package).
        self.ensure_desktop()
        q = shlex.quote(url)
        self._run(f"DISPLAY={self.display} CHROME=$(command -v google-chrome || command -v chromium || ls /ms-playwright/chromium-*/chrome-linux/chrome 2>/dev/null | head -1); nohup \"$CHROME\" --no-sandbox --disable-dev-shm-usage --disable-gpu {q} >/tmp/harness-browser.log 2>&1 & sleep 2")
        return True
