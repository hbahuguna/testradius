import hashlib
import hmac
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def _default_path() -> Path:
    override = os.environ.get("TIA_LICENSE_STATE_PATH")
    if override:
        return Path(override)
    return Path.home() / ".tia-agent" / "license.json"


@dataclass
class LicenseState:
    activation_token: str = ""
    license_key: str = ""
    device_fingerprint: str = ""
    subscription_status: str = ""
    quota_remaining: int = 0
    grace_until: str | None = None
    last_validated_at: str | None = None
    pending_runs: list[dict] = field(default_factory=list)

    @property
    def last_validated(self) -> datetime | None:
        if not self.last_validated_at:
            return None
        return datetime.fromisoformat(self.last_validated_at).astimezone(timezone.utc)


def _mac(data: dict, secret: str) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


class LicenseStore:
    def __init__(self, path: Path | None = None, secret: str | None = None):
        self.path = path or _default_path()
        self.secret = secret or "tia-agent-local-store-v1"

    def load(self) -> LicenseState:
        if not self.path.exists():
            return LicenseState()
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return LicenseState()
        mac = raw.pop("_mac", "")
        if not hmac.compare_digest(mac, _mac(raw, self.secret)):
            return LicenseState()
        known = {f: raw.get(f) for f in LicenseState.__dataclass_fields__}
        return LicenseState(**known)

    def save(self, state: LicenseState) -> None:
        data = asdict(state)
        data["_mac"] = _mac(data, self.secret)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
