"""Local sandbox provider (Docker-based)."""
from __future__ import annotations

from typing import Any, Dict

from .base import BaseSandboxProvider


class LocalSandboxProvider(BaseSandboxProvider):
    def create(self, template: str = "base", timeout: int = 300, **kwargs) -> str:
        return "local-sandbox"

    def kill(self, sandbox_id: str) -> bool:
        return True

    def run_command(self, sandbox_id: str, command: str, timeout: int = 60) -> Dict[str, Any]:
        return {"stdout": "", "stderr": "", "exit_code": 0}

    def upload_file(self, sandbox_id: str, path: str, content: bytes) -> bool:
        return True

    def download_file(self, sandbox_id: str, path: str) -> bytes:
        return b""

    def is_running(self, sandbox_id: str) -> bool:
        return True
