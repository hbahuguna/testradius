"""Portable secrets broker client (Vault dev backend).

Secrets are never logged. Values can be supplied from the environment for
tests; otherwise the client reads the KV v2 path from Vault.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger("cell.secrets")


class SecretError(Exception):
    pass


class VaultBroker:
    def __init__(self, addr: str | None = None, token: str | None = None, timeout: float = 1.0):
        self.addr = (addr or os.environ.get("CELL_VAULT_ADDR") or "http://vault:8200").rstrip("/")
        self.token = token or os.environ.get("CELL_VAULT_TOKEN") or "dev-root-token"
        self.timeout = timeout
        self._cache: dict[str, str] = {}

    def get_secret(self, path: str) -> str:
        if path in self._cache:
            return self._cache[path]

        env_key = f"CELL_SECRET_{path.replace('/', '_').upper()}"
        if env_key in os.environ:
            value = os.environ[env_key]
            self._cache[path] = value
            logger.info("secret_resolved path=%s source=env", path)
            return value

        try:
            response = httpx.get(
                f"{self.addr}/v1/secret/data/{path}",
                headers={"X-Vault-Token": self.token},
                timeout=self.timeout,
            )
            response.raise_for_status()
            value = response.json()["data"]["data"]["value"]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            logger.warning("secret_unavailable path=%s", path)
            raise SecretError(f"secret unavailable: {path}") from exc

        self._cache[path] = value
        logger.info("secret_resolved path=%s source=vault", path)
        return value

    def get_all(self, paths: list[str]) -> dict[str, str]:
        return {path: self.get_secret(path) for path in paths}
