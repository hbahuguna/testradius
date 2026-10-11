"""License guard: wraps tia-license-client for the agent CLI flow.

Handles the two license-relevant moments in an analyze run:
- BEFORE: ensure_valid() (daily validation / offline grace / expiry check)
- AFTER (success only): record_run() -> meters a TIA run against the server
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .config import TiaConfig, config_dir
from .errors import LicenseError
from .privacy import filter_license_metadata
from license_client import LicenseBlocked, LicenseClient, LicenseServerUnavailable
from license_client.store import LicenseStore


class LicenseGuard:
    def __init__(self, config: TiaConfig):
        self.config = config
        self._client: Optional[LicenseClient] = None

    def _get_client(self) -> LicenseClient:
        if self._client is None:
            self._client = LicenseClient(
                server_url=self.config.license_url,
                store=LicenseStore(path=self._state_path()),
            )
        return self._client

    @staticmethod
    def _state_path() -> Path:
        # Honor TIA_LICENSE_STATE_PATH, else keep license state beside the
        # agent config so TIA_CONFIG_HOME isolates state per environment.
        return Path(os.environ.get("TIA_LICENSE_STATE_PATH", config_dir() / "license.json"))

    def activate(self, license_key: str) -> dict:
        try:
            state = self._get_client().activate(license_key)
        except LicenseBlocked as e:
            raise LicenseError(str(e)) from e
        except LicenseServerUnavailable as e:
            raise LicenseError(f"License server unreachable: {e}") from e
        return {"subscription_status": state.subscription_status, "quota_remaining": state.quota_remaining}

    def status(self) -> dict:
        try:
            state = self._get_client().ensure_valid()
        except LicenseBlocked as e:
            return {"status": "blocked", "reason": str(e), "license_status": e.status}
        except LicenseServerUnavailable as e:
            return {"status": "unreachable", "reason": str(e)}
        return {"status": "valid", "subscription_status": state.subscription_status, "quota_remaining": state.quota_remaining}

    def ensure_valid(self) -> None:
        """Block early with a graceful message if the license cannot be used."""
        try:
            self._get_client().ensure_valid()
        except LicenseBlocked as e:
            raise LicenseError(str(e)) from e
        except LicenseServerUnavailable as e:
            # Offline grace handled inside ensure_valid; a bare unavailable is a config problem.
            raise LicenseError(f"License server unreachable: {e}") from e

    def record_run(self, run_id: str, repo_hash: str, metadata: dict) -> None:
        """Meter a completed run. Failures here are soft (don't fail the analysis).

        Only the D12 metadata allowlist is ever sent (defense in depth — the
        server filters again on receipt).
        """
        try:
            self._get_client().record_run(
                run_id=run_id,
                metadata=filter_license_metadata({"repo_hash": repo_hash, **metadata}),
            )
        except LicenseBlocked as e:
            # Run was completed successfully; just notify the user.
            raise LicenseError(f"Run completed but was not counted: {e}") from e
        except LicenseServerUnavailable as e:
            raise LicenseError(f"Run completed but could not be metered: {e}") from e