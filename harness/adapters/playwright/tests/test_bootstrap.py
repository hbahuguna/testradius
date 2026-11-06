"""Unit tests for Playwright bootstrap utilities."""
from unittest.mock import MagicMock

from harness.adapters.playwright.bootstrap import ensure_playwright_ready, is_playwright_ready
from harness.sandbox.base import BaseSandboxProvider


class MockProvider(BaseSandboxProvider):
    def __init__(self, ready: bool = True):
        self.ready = ready
        self.commands: list[str] = []
        self.files: dict[str, bytes] = {}

    def create(self, template: str = "base", timeout: int = 300, **kwargs) -> str:
        return "sbx-test"

    def kill(self, sandbox_id: str) -> bool:
        return True

    def run_command(self, sandbox_id: str, command: str, timeout: int = 60) -> dict:
        self.commands.append(command)
        if "echo READY" in command:
            if self.ready:
                return {"stdout": "READY", "stderr": "", "exit_code": 0}
            return {"stdout": "", "stderr": "Not ready", "exit_code": 1}
        return {"stdout": "DONE", "stderr": "", "exit_code": 0}

    def upload_file(self, sandbox_id: str, path: str, content: bytes) -> bool:
        self.files[path] = content
        return True

    def download_file(self, sandbox_id: str, path: str) -> bytes:
        return self.files.get(path, b"")

    def is_running(self, sandbox_id: str) -> bool:
        return True


def test_is_playwright_ready_true():
    provider = MockProvider(ready=True)
    assert is_playwright_ready(provider, "sbx-test") is True


def test_is_playwright_ready_false():
    provider = MockProvider(ready=False)
    assert is_playwright_ready(provider, "sbx-test") is False


def test_ensure_playwright_ready_already_ready():
    provider = MockProvider(ready=True)
    res = ensure_playwright_ready(provider, "sbx-test")
    assert res is True
    # Should only run check command
    assert len(provider.commands) == 1


def test_ensure_playwright_ready_runs_bootstrap():
    provider = MockProvider(ready=False)

    # Make provider become ready after bootstrap commands
    def fake_run(sandbox_id, command, timeout=60):
        provider.commands.append(command)
        if "echo READY" in command:
            # Become ready if apt and pip have been called
            has_pip = any("pip install" in c for c in provider.commands)
            has_hs = any("install_hs.sh" in c for c in provider.commands)
            if has_pip and has_hs:
                return {"stdout": "READY", "stderr": "", "exit_code": 0}
            return {"stdout": "", "stderr": "", "exit_code": 1}
        return {"stdout": "DONE", "stderr": "", "exit_code": 0}

    provider.run_command = fake_run

    res = ensure_playwright_ready(provider, "sbx-test")
    assert res is True
    assert any("pip install" in c for c in provider.commands)
    assert any("install_hs.sh" in c for c in provider.commands)
    assert any("apt-get install" in c for c in provider.commands)
