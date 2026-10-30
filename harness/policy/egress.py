"""Egress allowlists."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List
from urllib.parse import urlparse


DEFAULT_ALLOWLIST = [
    "testradius.dev",
    "www.testradius.dev",
    "localhost",
    "127.0.0.1",
]


class EgressBlocked(Exception):
    pass


@dataclass
class EgressPolicy:
    allowed_hosts: List[str] = field(default_factory=lambda: list(DEFAULT_ALLOWLIST))
    allow_subdomains: bool = True

    def is_allowed(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            if host in self.allowed_hosts:
                return True
            if self.allow_subdomains:
                for allowed in self.allowed_hosts:
                    if allowed and host.endswith("." + allowed):
                        return True
            return False
        except Exception:
            return False

    def enforce(self, url: str):
        if not self.is_allowed(url):
            raise EgressBlocked(f"Egress blocked: {url} not in allowlist")
        return True
