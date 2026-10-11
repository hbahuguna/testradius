"""API-key storage: OS keychain first, 0600 file fallback.

Backends:
  keychain   — macOS `security` generic password (service `tia-agent`)
  secret-tool— Linux/libsecret CLI when available
  file       — ~/.tia-agent/credentials.json, chmod 600

Override with TIA_CREDENTIALS_BACKEND=file|keychain|secret-tool (tests/CI use
`file`). Keys never enter config.json, source, or the binary.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

SERVICE = "tia-agent"

# Injection points for tests: command runner + config dir.
_Runner = Callable[..., "subprocess.CompletedProcess"]


def _default_runner(args: List[str], input: Optional[str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, input=input, capture_output=True, text=True, timeout=15)


def _config_dir() -> Path:
    return Path(os.environ.get("TIA_CONFIG_HOME", "~/.tia-agent")).expanduser()


class CredentialStore:
    def __init__(self, backend: Optional[str] = None, file_path: Optional[Path] = None,
                 runner: Optional[_Runner] = None):
        self._runner = runner or _default_runner
        name = backend or os.environ.get("TIA_CREDENTIALS_BACKEND") or self._auto_backend()
        self.backend_name = name
        if name == "keychain":
            self._impl: "_Backend" = KeychainBackend(self._runner)
        elif name == "secret-tool":
            self._impl = SecretToolBackend(self._runner)
        else:
            self._impl = FileBackend(file_path or (_config_dir() / "credentials.json"))

    @staticmethod
    def _auto_backend() -> str:
        if sys_platform() == "darwin" and shutil.which("security"):
            return "keychain"
        if shutil.which("secret-tool"):
            return "secret-tool"
        return "file"

    def get(self, provider: str) -> Optional[str]:
        return self._impl.get(provider)

    def set(self, provider: str, key: str) -> None:
        key = key.strip()
        if not key:
            raise ValueError("empty API key")
        self._impl.set(provider, key)

    def delete(self, provider: str) -> None:
        self._impl.delete(provider)

    def list_providers(self) -> List[str]:
        return self._impl.list_providers()


def sys_platform() -> str:
    import sys

    return sys.platform


class _Backend:
    name = "?"

    def get(self, provider: str) -> Optional[str]:
        raise NotImplementedError

    def set(self, provider: str, key: str) -> None:
        raise NotImplementedError

    def delete(self, provider: str) -> None:
        raise NotImplementedError

    def list_providers(self) -> List[str]:
        raise NotImplementedError


class KeychainBackend(_Backend):
    """macOS `security` generic-password store."""
    name = "keychain"

    def __init__(self, runner: _Runner = _default_runner):
        self._run = runner

    def get(self, provider: str) -> Optional[str]:
        p = self._run(["security", "find-generic-password", "-a", provider, "-s", SERVICE, "-w"])
        if p.returncode != 0:
            return None
        return p.stdout.strip() or None

    def set(self, provider: str, key: str) -> None:
        # `-w` as the final option with no value makes `security` read the
        # password from stdin (prompted twice: enter + retype), so the key
        # never appears in argv (`ps`) or shell history.
        p = self._run(["security", "add-generic-password", "-U", "-a", provider,
                       "-s", SERVICE, "-w"], input=f"{key}\n{key}\n")
        if p.returncode != 0:
            raise RuntimeError(f"keychain write failed: {p.stderr.strip() or p.stdout.strip()}")

    def delete(self, provider: str) -> None:
        self._run(["security", "delete-generic-password", "-a", provider, "-s", SERVICE])

    def list_providers(self) -> List[str]:
        # dump-keychain is noisy/unreliable for listing — probe known providers instead.
        return [p for p in ("openai", "anthropic", "google", "github") if self.get(p)]


class SecretToolBackend(_Backend):
    """Linux libsecret CLI store."""
    name = "secret-tool"

    def __init__(self, runner: _Runner = _default_runner):
        self._run = runner

    def get(self, provider: str) -> Optional[str]:
        p = self._run(["secret-tool", "lookup", "service", SERVICE, "account", provider])
        if p.returncode != 0:
            return None
        return p.stdout.strip() or None

    def set(self, provider: str, key: str) -> None:
        p = self._run(
            ["secret-tool", "store", "--label", f"{SERVICE} {provider}",
             "service", SERVICE, "account", provider],
            input=key,
        )
        if p.returncode != 0:
            raise RuntimeError(f"secret-tool write failed: {p.stderr.strip()}")

    def delete(self, provider: str) -> None:
        self._run(["secret-tool", "clear", "service", SERVICE, "account", provider])

    def list_providers(self) -> List[str]:
        return [p for p in ("openai", "anthropic", "google", "github") if self.get(p)]


class FileBackend(_Backend):
    """Last-resort file store, mode 0600. Format: {"openai": {"api_key": "..."}}."""
    name = "file"

    def __init__(self, path: Path):
        self.path = path

    def _read(self) -> Dict[str, Dict[str, str]]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self, data: Dict[str, Dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2))
        os.chmod(self.path, 0o600)

    def get(self, provider: str) -> Optional[str]:
        entry = self._read().get(provider) or {}
        return entry.get("api_key") or None

    def set(self, provider: str, key: str) -> None:
        data = self._read()
        data[provider] = {"api_key": key}
        self._write(data)

    def delete(self, provider: str) -> None:
        data = self._read()
        if provider in data:
            del data[provider]
            self._write(data)

    def list_providers(self) -> List[str]:
        return sorted(self._read().keys())