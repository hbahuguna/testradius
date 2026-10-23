"""Allowlist-based policy engine (v1: no general-purpose policy language)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""


class PolicyEngine:
    def __init__(self) -> None:
        self._version = 1
        self._allow_network = False
        self._allowed_hosts: set[str] = set()

    @property
    def version(self) -> int:
        return self._version

    def load(self, policy: dict) -> None:
        self._allow_network = bool(policy.get("allow_network", False))
        self._allowed_hosts = {str(host) for host in policy.get("allowed_hosts") or []}
        self._version += 1

    def reload(self) -> int:
        self._version += 1
        return self._version

    def check_network(self, host: str) -> PolicyDecision:
        if not self._allow_network:
            return PolicyDecision(False, "network_egress_denied")
        if self._allowed_hosts and host not in self._allowed_hosts:
            return PolicyDecision(False, "host_not_allowed")
        return PolicyDecision(True)
