"""E2B sandbox provider implementation."""
from __future__ import annotations

import os
from typing import Any, Dict

try:
    from e2b import Sandbox
except ImportError:
    Sandbox = None

from .base import BaseSandboxProvider


class E2BSandboxProvider(BaseSandboxProvider):
    """E2B implementation of sandbox provider."""

    def __init__(self, api_key: str | None = None, api_url: str | None = None):
        self.api_key = api_key or os.environ.get("E2B_API_KEY")
        self.api_url = api_url or os.environ.get("E2B_API_URL")
        self._sandboxes: Dict[str, Any] = {}

    def create(self, template: str = "base", timeout: int = 300, **kwargs) -> str:
        if Sandbox is None:
            raise RuntimeError("e2b package not installed")
        try:
            sbx = Sandbox.create(api_key=self.api_key, template=template, timeout=timeout)
            self._sandboxes[sbx.sandbox_id] = sbx
            return sbx.sandbox_id
        except Exception as e:
            raise RuntimeError(f"Failed to create E2B sandbox: {e}")

    def kill(self, sandbox_id: str) -> bool:
        try:
            if sandbox_id in self._sandboxes:
                self._sandboxes[sandbox_id].kill()
                del self._sandboxes[sandbox_id]
                return True
            # Try to create instance and kill
            if Sandbox:
                sbx = Sandbox.connect(sandbox_id, api_key=self.api_key)
                sbx.kill()
                return True
        except Exception:
            pass
        return False

    def run_command(self, sandbox_id: str, command: str, timeout: int = 60) -> Dict[str, Any]:
        try:
            sbx = self._sandboxes.get(sandbox_id)
            if not sbx and Sandbox:
                sbx = Sandbox.connect(sandbox_id, api_key=self.api_key)
                self._sandboxes[sandbox_id] = sbx
            result = sbx.commands.run(command, timeout=timeout)
            return {
                "stdout": getattr(result, "stdout", ""),
                "stderr": getattr(result, "stderr", ""),
                "exit_code": getattr(result, "exit_code", 0),
            }
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "exit_code": -1}

    def upload_file(self, sandbox_id: str, path: str, content: bytes) -> bool:
        try:
            sbx = self._sandboxes.get(sandbox_id)
            if not sbx and Sandbox:
                sbx = Sandbox.connect(sandbox_id, api_key=self.api_key)
                self._sandboxes[sandbox_id] = sbx
            sbx.files.write(path, content)
            return True
        except Exception:
            return False

    def download_file(self, sandbox_id: str, path: str) -> bytes:
        try:
            sbx = self._sandboxes.get(sandbox_id)
            if not sbx and Sandbox:
                sbx = Sandbox.connect(sandbox_id, api_key=self.api_key)
                self._sandboxes[sandbox_id] = sbx
            return sbx.files.read(path)
        except Exception:
            return b""

    def is_running(self, sandbox_id: str) -> bool:
        try:
            sbx = self._sandboxes.get(sandbox_id)
            if sbx:
                return sbx.is_running()
        except Exception:
            pass
        return False
