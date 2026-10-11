import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import Settings
from .models import Activation, License, Run, utcnow

GRACE_MESSAGE = (
    "Your subscription has expired. Your license remains usable for {days} more day(s) "
    "under the offline grace period (until {grace_until}). Please renew to continue."
)
EXPIRED_MESSAGE = (
    "Your subscription expired on {expired_at} and the grace period has ended. "
    "TIA runs are blocked until you renew your subscription."
)
QUOTA_EXCEEDED_MESSAGE = (
    "Run quota exhausted for the current subscription period ({quota} runs). "
    "Upgrade or wait for the next billing period."
)


@dataclass
class AccessDecision:
    allowed: bool
    status: str
    quota_remaining: int
    grace_until: datetime | None
    message: str | None = None


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def evaluate_access(
    license: License,
    settings: Settings,
    now: datetime,
    runs_this_period: int,
) -> AccessDecision:
    quota_remaining = max(0, license.runs_quota - runs_this_period)
    grace_until: datetime | None = None

    if license.current_period_end is not None:
        period_end = _ensure_aware(license.current_period_end)
        grace_until = period_end + timedelta(days=settings.grace_days)
        if now > grace_until:
            return AccessDecision(
                allowed=False,
                status="expired",
                quota_remaining=quota_remaining,
                grace_until=grace_until,
                message=EXPIRED_MESSAGE.format(expired_at=period_end.date().isoformat()),
            )
        if now > period_end:
            days_left = (grace_until - now).days + 1
            return AccessDecision(
                allowed=True,
                status="grace",
                quota_remaining=quota_remaining,
                grace_until=grace_until,
                message=GRACE_MESSAGE.format(days=days_left, grace_until=grace_until.date().isoformat()),
            )

    if license.subscription_status in ("canceled", "incomplete", "unpaid"):
        status = license.subscription_status
        now_aware = now
        grace_until = now_aware + timedelta(days=settings.grace_days)
        return AccessDecision(
            allowed=True,
            status=status,
            quota_remaining=quota_remaining,
            grace_until=grace_until,
            message=GRACE_MESSAGE.format(
                days=settings.grace_days, grace_until=grace_until.date().isoformat()
            ),
        )

    if quota_remaining <= 0:
        return AccessDecision(
            allowed=False,
            status=license.subscription_status,
            quota_remaining=0,
            grace_until=grace_until,
            message=QUOTA_EXCEEDED_MESSAGE.format(quota=license.runs_quota),
        )

    return AccessDecision(
        allowed=True,
        status=license.subscription_status,
        quota_remaining=quota_remaining,
        grace_until=grace_until,
    )


def count_runs_this_period(db: Session, license: License) -> int:
    stmt = select(func.count(Run.id)).where(Run.license_id == license.id)
    if license.current_period_start is not None:
        stmt = stmt.where(Run.created_at >= _ensure_aware(license.current_period_start))
    else:
        stmt = stmt.where(Run.created_at >= _ensure_aware(license.created_at))
    return db.execute(stmt).scalar_one()


def activate(
    db: Session,
    settings: Settings,
    license_key: str,
    device_fingerprint: str,
) -> tuple[Activation, AccessDecision, str] | None:
    """Activate a device. Returns (activation, decision, plaintext_token).

    The plaintext token is returned exactly once here and stored only as a hash.
    None means unknown license key or device limit reached.
    """
    license = db.execute(
        select(License).where(License.license_key == license_key)
    ).scalar_one_or_none()
    if license is None:
        return None

    runs = count_runs_this_period(db, license)
    decision = evaluate_access(license, settings, utcnow(), runs)

    activation = db.execute(
        select(Activation).where(
            Activation.license_id == license.id,
            Activation.device_fingerprint == device_fingerprint,
        )
    ).scalar_one_or_none()

    if activation is None:
        device_count = db.execute(
            select(func.count(Activation.id)).where(Activation.license_id == license.id)
        ).scalar_one()
        if device_count >= license.device_limit:
            return None
        activation = Activation(
            license_id=license.id,
            device_fingerprint=device_fingerprint,
            token_hash="",
        )
        db.add(activation)

    token = Activation.new_token()
    activation.token_hash = hash_token(token)
    activation.last_seen_at = utcnow()
    db.commit()
    db.refresh(activation)
    return activation, decision, token


def validate(
    db: Session,
    settings: Settings,
    activation_token: str,
) -> tuple[License, AccessDecision] | None:
    activation = db.execute(
        select(Activation).where(Activation.token_hash == hash_token(activation_token))
    ).scalar_one_or_none()
    if activation is None:
        return None

    license = db.get(License, activation.license_id)
    if license is None:
        return None

    runs = count_runs_this_period(db, license)
    decision = evaluate_access(license, settings, utcnow(), runs)
    activation.last_seen_at = utcnow()
    db.commit()
    return license, decision


def record_run(
    db: Session,
    settings: Settings,
    activation_token: str,
    run_id: str,
    metadata: dict | None = None,
) -> tuple[bool, AccessDecision | None, str | None]:
    """Record a billable TIA run. Returns (recorded, decision, error_code).

    Only successful TIA runs should call this. Idempotent per run_id.
    """
    result = validate(db, settings, activation_token)
    if result is None:
        return False, None, "invalid_token"
    license, decision = result
    if not decision.allowed:
        return False, decision, "blocked"

    existing = db.execute(select(Run).where(Run.run_id == run_id)).scalar_one_or_none()
    if existing is not None:
        return True, decision, None

    runs = count_runs_this_period(db, license)
    if runs >= license.runs_quota:
        decision = evaluate_access(license, settings, utcnow(), runs)
        return False, decision, "quota_exceeded"

    safe_meta = _metadata_allowlist(metadata)
    db.add(Run(license_id=license.id, run_id=run_id, metadata_json=safe_meta))
    db.commit()

    runs = count_runs_this_period(db, license)
    decision = evaluate_access(license, settings, utcnow(), runs)
    return True, decision, None


def _metadata_allowlist(metadata: dict | None) -> dict | None:
    """License server sees metadata only — never repo content (D12)."""
    if not metadata:
        return None
    allowed = {
        "repo_hash",
        "file_count",
        "test_count",
        "language",
        "duration_seconds",
        "os",
        "agent_version",
    }
    return {k: v for k, v in metadata.items() if k in allowed}
