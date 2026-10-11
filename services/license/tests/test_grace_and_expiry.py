from datetime import datetime, timedelta, timezone

from license_server.models import License, utcnow
from license_server.service import GRACE_MESSAGE, EXPIRED_MESSAGE, evaluate_access, hash_token
from license_server.config import Settings


def _settings(grace_days=3):
    return Settings(
        database_url="sqlite://",
        admin_token="t",
        stripe_webhook_secret="",
        grace_days=grace_days,
        default_device_limit=3,
        default_runs_per_period=5,
    )


def _license(period_end, status="active", quota=5):
    return License(
        license_key="TIA-x",
        subscription_status=status,
        runs_quota=quota,
        device_limit=3,
        current_period_end=period_end,
        created_at=utcnow(),
    )


NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def test_within_period_is_active():
    decision = evaluate_access(_license(NOW + timedelta(days=10)), _settings(), NOW, 0)
    assert decision.allowed
    assert decision.status == "active"
    assert decision.message is None


def test_within_grace_allows_with_message():
    period_end = NOW - timedelta(days=1)
    decision = evaluate_access(_license(period_end), _settings(), NOW, 0)
    assert decision.allowed
    assert decision.status == "grace"
    assert decision.grace_until == period_end + timedelta(days=3)
    assert "renew" in decision.message.lower()
    assert GRACE_MESSAGE.split("{")[0].strip()[:20] in decision.message


def test_beyond_grace_blocks_with_graceful_message():
    """AC (L1): block when subscription expired beyond grace, with graceful message."""
    period_end = NOW - timedelta(days=4)  # 4 days ago, grace = 3 days
    decision = evaluate_access(_license(period_end), _settings(), NOW, 0)
    assert not decision.allowed
    assert decision.status == "expired"
    assert decision.message is not None
    assert "expired" in decision.message.lower()
    assert "renew" in decision.message.lower()


def test_exactly_at_grace_edge_allows():
    period_end = NOW - timedelta(days=3)
    decision = evaluate_access(_license(period_end), _settings(), NOW, 0)
    assert decision.allowed
    assert decision.status == "grace"


def test_one_day_past_grace_blocks():
    period_end = NOW - timedelta(days=3) - timedelta(seconds=1)
    decision = evaluate_access(_license(period_end), _settings(), NOW, 0)
    assert not decision.allowed


def test_no_period_end_is_active():
    decision = evaluate_access(_license(None), _settings(), NOW, 0)
    assert decision.allowed
    assert decision.status == "active"


def test_canceled_subscription_enters_grace():
    decision = evaluate_access(_license(None, status="canceled"), _settings(), NOW, 0)
    assert decision.allowed
    assert decision.status == "canceled"
    assert decision.grace_until == NOW + timedelta(days=3)


def test_quota_exhausted_blocks():
    decision = evaluate_access(_license(None, quota=5), _settings(), NOW, 5)
    assert not decision.allowed
    assert decision.quota_remaining == 0
    assert "quota" in decision.message.lower()


def test_naive_datetime_treated_as_utc():
    naive_end = (NOW - timedelta(days=4)).replace(tzinfo=None)
    decision = evaluate_access(_license(naive_end), _settings(), NOW, 0)
    assert not decision.allowed
