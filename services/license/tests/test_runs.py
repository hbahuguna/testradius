from datetime import datetime, timedelta, timezone

from license_server.models import License, Run, utcnow


def _activate(client, license_key, device="device-abc-12345"):
    return client.post(
        "/v1/activations",
        json={"license_key": license_key, "device_fingerprint": device},
    ).json()["activation_token"]


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_successful_run_is_counted_once(client, license_key):
    """AC (L2): a TIA run is metered; repeat of same run_id is idempotent."""
    token = _activate(client, license_key)
    resp = client.post(
        "/v1/runs",
        headers=_headers(token),
        json={"run_id": "run-abc-0001", "metadata": {"repo_hash": "deadbeef", "file_count": 3}},
    )
    assert resp.status_code == 200
    assert resp.json()["recorded"] is True
    assert resp.json()["quota_remaining"] == 4

    again = client.post(
        "/v1/runs",
        headers=_headers(token),
        json={"run_id": "run-abc-0001", "metadata": {"repo_hash": "deadbeef"}},
    )
    assert again.json()["quota_remaining"] == 4  # idempotent, not double counted


def test_quota_exhaustion_blocks_and_message_is_graceful(client, license_key):
    token = _activate(client, license_key)
    for i in range(5):
        resp = client.post(
            "/v1/runs",
            headers=_headers(token),
            json={"run_id": f"run-{i:04d}-xxxx"},
        )
        assert resp.status_code == 200
    blocked = client.post(
        "/v1/runs",
        headers=_headers(token),
        json={"run_id": "run-0005-xxxx"},
    )
    assert blocked.status_code == 403
    assert "quota" in blocked.json()["detail"].lower()


def test_run_requires_valid_token(client):
    resp = client.post(
        "/v1/runs",
        headers=_headers("bogus"),
        json={"run_id": "run-abc-0001"},
    )
    assert resp.status_code == 401


def test_metadata_allowlist_strips_repo_content(client, license_key):
    """D12: license server sees metadata only — never repo content."""
    token = _activate(client, license_key)
    client.post(
        "/v1/runs",
        headers=_headers(token),
        json={
            "run_id": "run-meta-0001",
            "metadata": {
                "repo_hash": "abc123",
                "file_count": 12,
                "source_code": "def secret(): pass",
                "diff": "--- a/file.py",
            },
        },
    )
    from license_server.models import Run

    with client.app.state.SessionLocal() as db:
        run = db.query(Run).filter(Run.run_id == "run-meta-0001").one()
        assert run.metadata_json == {"repo_hash": "abc123", "file_count": 12}


def _add_license(app, *, period_end):
    from license_server.models import generate_license_key

    key = generate_license_key()
    with app.state.SessionLocal() as db:
        db.add(
            License(
                license_key=key,
                subscription_status="active",
                runs_quota=5,
                device_limit=3,
                current_period_end=period_end,
                created_at=utcnow(),
            )
        )
        db.commit()
    return key


def _expire_license(app, key, period_end):
    with app.state.SessionLocal() as db:
        lic = db.query(License).filter(License.license_key == key).one()
        lic.current_period_end = period_end
        db.commit()


def _runs_for(app, key):
    with app.state.SessionLocal() as db:
        lic = db.query(License).filter(License.license_key == key).one()
        return db.query(Run).filter(Run.license_id == lic.id).count()


def test_run_blocked_and_not_counted_when_expired_mid_session(client, app):
    """E7/E2: subscription lapses mid-session -> run record is rejected, not counted."""
    key = _add_license(app, period_end=datetime.now(timezone.utc) + timedelta(days=10))
    token = _activate(client, key)

    # The subscription lapses after the device is already activated.
    _expire_license(app, key, datetime.now(timezone.utc) - timedelta(days=4))

    resp = client.post(
        "/v1/runs",
        headers=_headers(token),
        json={"run_id": "run-midsession-01"},
    )
    assert resp.status_code == 403
    assert "renew" in resp.json()["detail"].lower()
    assert _runs_for(app, key) == 0


def test_run_within_grace_is_counted(client, app):
    """E7/E2: within the 3-day grace window a run still meters."""
    key = _add_license(app, period_end=datetime.now(timezone.utc) - timedelta(days=1))
    token = _activate(client, key)

    resp = client.post(
        "/v1/runs",
        headers=_headers(token),
        json={"run_id": "run-grace-0001"},
    )
    assert resp.status_code == 200
    assert resp.json()["recorded"] is True
    assert _runs_for(app, key) == 1

