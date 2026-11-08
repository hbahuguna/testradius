"""Configuration for Gemini computer-use spike (env refs only — never secrets)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class ComputerUseConfig:
    """Runtime config for spike (008.4). Secrets only via env var *names*."""

    gemini_model: str = field(default_factory=lambda: os.environ.get("GEMINI_COMPUTER_USE_MODEL") or os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash")
    gemini_api_key_env: str = "GEMINI_API_KEY"  # or GOOGLE_API_KEY alias
    gemini_api_key: str | None = None  # resolved at startup from env if not passed

    e2b_template: str = field(default_factory=lambda: os.environ.get("E2B_DESKTOP_TEMPLATE", "desktop-chromium"))
    e2b_api_key_env: str = "E2B_API_KEY"
    e2b_api_url: str | None = field(default_factory=lambda: os.environ.get("E2B_API_URL"))
    e2b_domain: str | None = field(default_factory=lambda: os.environ.get("E2B_DOMAIN") or "8.231.230.69.nip.io:3002")
    e2b_cpu: int = field(default_factory=lambda: int(os.environ.get("E2B_CPU_COUNT", "2")))
    e2b_memory_mb: int = field(default_factory=lambda: int(os.environ.get("E2B_MEMORY_MB", "2048")))

    screen_width: int = 1440
    screen_height: int = 900
    sandbox_timeout_s: int = 2400  # bootstrap (apt + playwright chromium ~5-10 min) + live run on self-hosted
    browser_bin: str = "google-chrome"
    browser_args: tuple[str, ...] = ("--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--start-maximized")
    display: str = ":99"

    def resolve_gemini_key(self) -> str | None:
        if self.gemini_api_key:
            return self.gemini_api_key
        return os.environ.get(self.gemini_api_key_env) or os.environ.get("GOOGLE_API_KEY")

    def resolve_e2b_key(self) -> str | None:
        return os.environ.get(self.e2b_api_key_env)

    def to_safe_dict(self) -> dict:
        # Never include resolved secrets.
        return {
            "gemini_model": self.gemini_model,
            "gemini_api_key_env": self.gemini_api_key_env,
            "has_gemini_key": bool(self.resolve_gemini_key()),
            "e2b_template": self.e2b_template,
            "e2b_api_url": self.e2b_api_url,
            "e2b_domain": self.e2b_domain,
            "e2b_cpu": self.e2b_cpu,
            "e2b_memory_mb": self.e2b_memory_mb,
            "has_e2b_key": bool(self.resolve_e2b_key()),
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "sandbox_timeout_s": self.sandbox_timeout_s,
        }
