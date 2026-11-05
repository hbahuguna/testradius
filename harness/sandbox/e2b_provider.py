"""E2B sandbox provider implementation."""
from __future__ import annotations

import os
from typing import Any, Dict

try:
    from e2b import Sandbox
    from e2b import connection_config as _e2b_cc
except ImportError:
    Sandbox = None
    _e2b_cc = None

from .base import BaseSandboxProvider

_PATCHED = False


def _patch_e2b_http_for_self_hosted() -> None:
    """Patch E2B SDK to use HTTP for self-hosted proxy (non-default port/domain)."""
    global _PATCHED
    if _PATCHED or _e2b_cc is None:
        return
    orig_url = _e2b_cc.ConnectionConfig.get_sandbox_url
    orig_direct = _e2b_cc.ConnectionConfig.get_sandbox_direct_url
    orig_host = _e2b_cc.ConnectionConfig.get_host

    def _http_url(self, sandbox_id, sandbox_domain, port=None):
        port = self.envd_port if port is None else port
        if self._sandbox_url:
            return self._sandbox_url
        host = orig_host(self, sandbox_id, sandbox_domain, port)
        # Use HTTP for self-hosted proxy when domain includes a port or E2B_SECURE=false
        domain = sandbox_domain or self.domain or ""
        use_http = (
            ":" in str(domain).split("@")[-1]
            or os.environ.get("E2B_SECURE", "").lower() in ("0", "false", "no")
            or (self.api_url or "").startswith("http://")
        )
        return f"http://{host}" if use_http else orig_url(self, sandbox_id, sandbox_domain, port)

    _e2b_cc.ConnectionConfig.get_sandbox_url = _http_url
    _e2b_cc.ConnectionConfig.get_sandbox_direct_url = _http_url
    _PATCHED = True


class E2BSandboxProvider(BaseSandboxProvider):
    """E2B implementation of sandbox provider."""

    def __init__(self, api_key: str | None = None, api_url: str | None = None, domain: str | None = None):
        self.api_key = api_key or os.environ.get("E2B_API_KEY")
        self.api_url = api_url or os.environ.get("E2B_API_URL")
        self.domain = domain or os.environ.get("E2B_DOMAIN")
        self._sandboxes: Dict[str, Any] = {}
        _patch_e2b_http_for_self_hosted()

    def _sdk_kwargs(self) -> Dict[str, Any]:
        kw: Dict[str, Any] = {"api_key": self.api_key}
        if self.domain:
            kw["domain"] = self.domain
        if self.api_url:
            kw["api_url"] = self.api_url
        return kw

    def create(self, template: str = "base", timeout: int = 300, **kwargs) -> str:
        if Sandbox is None:
            raise RuntimeError("e2b package not installed")
        try:
            sbx = Sandbox.create(template=template, timeout=timeout, **self._sdk_kwargs(), **kwargs)
            self._sandboxes[sbx.sandbox_id] = sbx
            return sbx.sandbox_id
        except Exception as e:
            raise RuntimeError(f"Failed to create E2B sandbox: {e}")

    def _get_sandbox(self, sandbox_id: str):
        sbx = self._sandboxes.get(sandbox_id)
        if not sbx and Sandbox:
            sbx = Sandbox.connect(sandbox_id, **self._sdk_kwargs())
            self._sandboxes[sandbox_id] = sbx
        return sbx

    def kill(self, sandbox_id: str) -> bool:
        try:
            if sandbox_id in self._sandboxes:
                self._sandboxes[sandbox_id].kill()
                del self._sandboxes[sandbox_id]
                return True
            if Sandbox:
                sbx = Sandbox.connect(sandbox_id, **self._sdk_kwargs())
                sbx.kill()
                return True
        except Exception:
            pass
        return False

    def run_command(self, sandbox_id: str, command: str, timeout: int = 60) -> Dict[str, Any]:
        try:
            sbx = self._get_sandbox(sandbox_id)
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
            sbx = self._get_sandbox(sandbox_id)
            sbx.files.write(path, content)
            return True
        except Exception:
            return False

    def download_file(self, sandbox_id: str, path: str) -> bytes:
        try:
            sbx = self._get_sandbox(sandbox_id)
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
