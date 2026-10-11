from datetime import datetime, timedelta, timezone

import httpx

from .fingerprint import device_fingerprint
from .store import LicenseState, LicenseStore


class LicenseBlocked(Exception):
    def __init__(self, message: str, status: str = "expired"):
        super().__init__(message)
        self.status = status


class LicenseServerUnavailable(Exception):
    """Server unreachable — caller may proceed under offline grace if eligible."""


def _status_from_message(detail: str) -> str:
    """Map the server's human message to a machine status (403 body has no status field)."""
    m = detail.lower()
    if "quota" in m:
        return "quota_exceeded"
    if "expired" in m or "renew" in m:
        return "expired"
    if "not activated" in m:
        return "not_activated"
    if "grace" in m:
        return "offline_grace_exceeded"
    return "blocked"


OFFLINE_GRACE_DAYS = 3
VALIDATE_INTERVAL = timedelta(hours=24)


class LicenseClient:
    def __init__(
        self,
        server_url: str,
        store: LicenseStore | None = None,
        fingerprint: str | None = None,
        now: datetime | None = None,
        timeout: float = 10.0,
    ):
        self.server_url = server_url.rstrip("/")
        self.store = store or LicenseStore()
        self._fingerprint = fingerprint
        self._now = now
        self._timeout = timeout

    @property
    def now(self) -> datetime:
        return (self._now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    @property
    def fingerprint(self) -> str:
        if self._fingerprint is None:
            self._fingerprint = device_fingerprint()
        return self._fingerprint

    def _get_state(self) -> LicenseState:
        return self.store.load()

    def _post(self, path: str, body: dict, token: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            resp = httpx.post(
                f"{self.server_url}{path}", json=body, headers=headers, timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            raise LicenseServerUnavailable(str(exc)) from exc
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            if resp.status_code == 403:
                raise LicenseBlocked(str(detail), status=_status_from_message(str(detail)))
            if resp.status_code == 401:
                raise LicenseBlocked("Activation token invalid. Please re-activate.", status="invalid")
            raise LicenseBlocked(str(detail), status=f"http_{resp.status_code}")
        return resp.json()

    def _get(self, path: str, token: str) -> dict:
        try:
            resp = httpx.get(
                f"{self.server_url}{path}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise LicenseServerUnavailable(str(exc)) from exc
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            if resp.status_code == 401:
                raise LicenseBlocked("Activation token invalid. Please re-activate.", status="invalid")
            if resp.status_code == 403:
                raise LicenseBlocked(str(detail), status=_status_from_message(str(detail)))
            raise LicenseBlocked(str(detail))
        return resp.json()

    def activate(self, license_key: str) -> LicenseState:
        data = self._post(
            "/v1/activations",
            {"license_key": license_key, "device_fingerprint": self.fingerprint},
        )
        state = self._get_state()
        state.activation_token = data["activation_token"]
        state.license_key = license_key
        state.device_fingerprint = self.fingerprint
        state.subscription_status = data.get("subscription_status", "active")
        state.quota_remaining = int(data.get("quota_remaining", 0))
        state.grace_until = data.get("grace_until")
        state.last_validated_at = self.now.isoformat()
        self.store.save(state)
        return state

    def ensure_valid(self) -> LicenseState:
        """Daily validation with 3-day offline grace (AC: validate daily, 3-day grace).

        Raises LicenseBlocked when the subscription is expired beyond grace or
        the server explicitly rejects us. Falls back to cached state while the
        server is unreachable, but only within the offline grace window.
        """
        state = self._get_state()
        if not state.activation_token:
            raise LicenseBlocked("Not activated. Provide a license key to activate.", status="not_activated")

        last = state.last_validated
        # Quota exhaustion and renewal both need server truth before any work
        # is done — a cached 0 must not block a renewed subscription, and a
        # cached positive must not let an exhausted quota start a run.
        needs_refresh = (
            last is None
            or (self.now - last) >= VALIDATE_INTERVAL
            or state.quota_remaining <= 0
        )

        if needs_refresh:
            try:
                data = self._get("/v1/validate", state.activation_token)
            except LicenseServerUnavailable:
                state = self._offline_grace(state)
                self._require_quota(state)
                return state
            except LicenseBlocked as exc:
                if exc.status == "invalid":
                    self.store.clear()
                raise
            state.subscription_status = data.get("subscription_status", "active")
            state.quota_remaining = int(data.get("quota_remaining", 0))
            state.grace_until = data.get("grace_until")
            state.last_validated_at = self.now.isoformat()
            self.store.save(state)
            self._require_quota(state)
            return state
        self._require_quota(state)
        return state

    def _require_quota(self, state: LicenseState) -> None:
        if state.quota_remaining <= 0:
            raise LicenseBlocked(
                "Run quota exhausted for the current subscription period. "
                "Upgrade or wait for the next billing period.",
                status="quota_exceeded",
            )

    def _offline_grace(self, state: LicenseState) -> LicenseState:
        last = state.last_validated
        if last is None:
            raise LicenseBlocked(
                "License server unreachable and no prior validation on record. "
                "Re-activate when online.",
                status="unreachable",
            )
        age = self.now - last
        if age > timedelta(days=OFFLINE_GRACE_DAYS):
            raise LicenseBlocked(
                "License server unreachable and offline grace period (3 days) has "
                "elapsed. Reconnect to validate your subscription.",
                status="offline_grace_exceeded",
            )
        return state

    def record_run(self, run_id: str, metadata: dict | None = None) -> LicenseState:
        """Meter a completed TIA run (D1: only successful runs are recorded).

        Offline runs are queued in the local store and flushed on next call.
        """
        state = self.ensure_valid()
        state = self._flush_pending(state)

        if state.quota_remaining <= 0:
            raise LicenseBlocked(
                "Run quota exhausted for the current subscription period. "
                "Upgrade or wait for the next billing period.",
                status="quota_exceeded",
            )

        entry = {"run_id": run_id, "metadata": metadata or {}}
        try:
            data = self._post(
                "/v1/runs",
                {"run_id": run_id, "metadata": metadata or {}},
                token=state.activation_token,
            )
        except LicenseServerUnavailable:
            state.pending_runs.append(entry)
            self.store.save(state)
            return state

        state.quota_remaining = int(data.get("quota_remaining", max(0, state.quota_remaining - 1)))
        self.store.save(state)
        return state

    def _flush_pending(self, state: LicenseState) -> LicenseState:
        if not state.pending_runs:
            return state
        remaining: list[dict] = []
        for entry in state.pending_runs:
            try:
                data = self._post(
                    "/v1/runs",
                    {"run_id": entry["run_id"], "metadata": entry.get("metadata") or {}},
                    token=state.activation_token,
                )
                state.quota_remaining = int(data.get("quota_remaining", state.quota_remaining))
            except LicenseBlocked:
                raise
            except LicenseServerUnavailable:
                remaining.append(entry)
        state.pending_runs = remaining
        self.store.save(state)
        return state
