import time

from license_server.models import License, utcnow


def test_admin_requires_token(client):
    resp = client.post(
        "/v1/admin/licenses",
        headers={"Authorization": "Bearer wrong"},
        json={"email": "a@b.c"},
    )
    assert resp.status_code == 403


def test_admin_disabled_without_config(tmp_path):
    from fastapi.testclient import TestClient

    from license_server.app import create_app
    from license_server.config import Settings

    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path}/admin.db",
            admin_token="",
            stripe_webhook_secret="",
            grace_days=3,
            default_device_limit=3,
            default_runs_per_period=500,
        )
    )
    resp = TestClient(app).post(
        "/v1/admin/licenses",
        headers={"Authorization": "Bearer x"},
        json={"email": "a@b.c"},
    )
    assert resp.status_code == 503


def test_admin_creates_license_and_it_activates(client, license_key):
    created = client.post(
        "/v1/admin/licenses",
        headers={"Authorization": "Bearer test-admin-token"},
        json={"email": "new@example.com", "runs_quota": 10},
    )
    assert created.status_code == 201
    key = created.json()["license_key"]
    activation = client.post(
        "/v1/activations",
        json={"license_key": key, "device_fingerprint": "device-new-12345"},
    )
    assert activation.status_code == 200
    assert activation.json()["quota_remaining"] == 10


def _stripe_event(sub_id: str, status: str, period_end: int, sig_secret: str = ""):
    import json

    payload = json.dumps(
        {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": sub_id,
                    "status": status,
                    "current_period_start": int(time.time()) - 100,
                    "current_period_end": period_end,
                }
            },
        }
    ).encode()
    return payload, _sign(payload, sig_secret)


def _sign(payload: bytes, sig_secret: str) -> str:
    import hashlib
    import hmac

    if not sig_secret:
        return ""
    ts = str(int(time.time()))
    sig = hmac.new(sig_secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def test_stripe_webhook_updates_subscription(app, client, license_key):
    with app.state.SessionLocal() as db:
        lic = db.query(License).first()
        lic.stripe_subscription_id = "sub_123"
        db.commit()

    payload, sig = _stripe_event("sub_123", "canceled", int(time.time()) + 3600)
    resp = client.post(
        "/v1/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": sig},
    )
    assert resp.status_code == 200
    with app.state.SessionLocal() as db:
        lic = db.query(License).first()
        assert lic.subscription_status == "canceled"


def test_stripe_signature_verification_required(tmp_path):
    from fastapi.testclient import TestClient

    from license_server.app import create_app
    from license_server.config import Settings

    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path}/sig.db",
            admin_token="t",
            stripe_webhook_secret="whsec_test",
            grace_days=3,
            default_device_limit=3,
            default_runs_per_period=500,
        )
    )
    client = TestClient(app)
    payload, _ = _stripe_event("sub_x", "active", int(time.time()) + 3600)
    bad = client.post(
        "/v1/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": "t=1,v1=bad"},
    )
    assert bad.status_code == 400
    good_sig = _sign(payload, "whsec_test")
    good = client.post(
        "/v1/webhooks/stripe",
        content=payload,
        headers={"stripe-signature": good_sig},
    )
    assert good.status_code == 200
