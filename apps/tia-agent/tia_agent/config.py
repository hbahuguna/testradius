"""Agent configuration: radius backend URL/token, license server URL."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, fields
from pathlib import Path

def config_dir() -> Path:
    """Resolved on every call so runtime TIA_CONFIG_HOME changes are honored."""
    return Path(os.environ.get("TIA_CONFIG_HOME", "~/.tia-agent")).expanduser()


def default_config_path() -> Path:
    return config_dir() / "config.json"


def data_dir() -> Path:
    """Backend data dir (postgres/neo4j volumes, generated compose)."""
    return config_dir() / "data"


_ENV_KEYS = ("TIA_RADIUS_URL", "TIA_RADIUS_TOKEN", "TIA_LICENSE_URL", "TIA_GITHUB_TOKEN",
             "TIA_VERBOSE", "TIA_LLM_PROVIDER", "TIA_LLM_MODEL", "TIA_REPO_PATH")

_FIELD_ENV = {
    "radius_url": "TIA_RADIUS_URL",
    "radius_token": "TIA_RADIUS_TOKEN",
    "license_url": "TIA_LICENSE_URL",
    "github_token": "TIA_GITHUB_TOKEN",
    "verbose": "TIA_VERBOSE",
    "llm_provider": "TIA_LLM_PROVIDER",
    "llm_model": "TIA_LLM_MODEL",
    "repo_path": "TIA_REPO_PATH",
}


def _coerce(env_name: str, value: str, _type: object) -> object:
    if env_name == "TIA_VERBOSE":
        return value in ("1", "true", "yes")
    return value


@dataclass
class TiaConfig:
    radius_url: str = os.environ.get("TIA_RADIUS_URL", "http://localhost:8000")
    radius_token: str = os.environ.get("TIA_RADIUS_TOKEN", "")
    license_url: str = os.environ.get("TIA_LICENSE_URL", "http://localhost:8100")
    github_token: str = os.environ.get("TIA_GITHUB_TOKEN", "")
    verbose: bool = os.environ.get("TIA_VERBOSE", "0") in ("1", "true", "yes")
    # LLM selection only — API keys live in the credential store, never here.
    llm_provider: str = os.environ.get("TIA_LLM_PROVIDER", "")
    llm_model: str = os.environ.get("TIA_LLM_MODEL", "")
    # Local checkout root (validation + deterministic fallback); empty = skip.
    repo_path: str = os.environ.get("TIA_REPO_PATH", "")

    @staticmethod
    def _env_prefix_used() -> bool:
        # True when any config-carrying TIA_* env var is set (env wins over file).
        return any(k in os.environ for k in _ENV_KEYS)

    @classmethod
    def load(cls, path: Path | None = None) -> "TiaConfig":
        if path is None:
            path = default_config_path()
        cfg = cls()
        if path.exists():
            raw = json.loads(path.read_text())
            # Env wins over file; file wins over defaults.
            env_set = cls._env_prefix_used()
            for f in fields(cls):
                if f.name in raw and not env_set:
                    setattr(cfg, f.name, raw[f.name])
        # Re-read env now (dataclass defaults are evaluated at import time).
        for f in fields(cls):
            env_name = _FIELD_ENV.get(f.name)
            if env_name and env_name in os.environ:
                setattr(cfg, f.name, _coerce(env_name, os.environ[env_name], f.type))
        return cfg

    def save(self, path: Path | None = None) -> Path:
        if path is None:
            path = default_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, default=str))
        return path