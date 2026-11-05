"""Base sandbox provider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseSandboxProvider(ABC):
    """Abstract interface for sandbox providers."""

    @abstractmethod
    def create(self, template: str = "base", timeout: int = 300, **kwargs) -> str:
        """Create a sandbox and return sandbox_id."""
        raise NotImplementedError

    @abstractmethod
    def kill(self, sandbox_id: str) -> bool:
        """Kill/destroy a sandbox."""
        raise NotImplementedError

    @abstractmethod
    def run_command(self, sandbox_id: str, command: str, timeout: int = 60) -> Dict[str, Any]:
        """Run a command in sandbox."""
        raise NotImplementedError

    @abstractmethod
    def upload_file(self, sandbox_id: str, path: str, content: bytes) -> bool:
        """Upload a file to sandbox."""
        raise NotImplementedError

    @abstractmethod
    def download_file(self, sandbox_id: str, path: str) -> bytes:
        """Download a file from sandbox."""
        raise NotImplementedError

    @abstractmethod
    def is_running(self, sandbox_id: str) -> bool:
        """Check if sandbox is running."""
        raise NotImplementedError
