import atexit
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

# Reuse the license server package from services/license (same repo).
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[3] / "services" / "license"
sys.path.insert(0, str(SERVER_DIR))

from license_server.app import create_app  # noqa: E402
from license_server.config import Settings  # noqa: E402
from license_server.models import License, utcnow  # noqa: E402

import uvicorn  # noqa: E402

from license_client import LicenseBlocked, LicenseClient, LicenseStore  # noqa: E402


class _ServerThread:
    def __init__(self, app, port: int):
        self.port = port
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self):
        self.thread.start()
        deadline = time.time() + 15
        while time.time() < deadline:
            if self.server.started:
                return
            time.sleep(0.1)
        raise RuntimeError("license server failed to start")

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("licsrv")
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/client_integration.db",
        admin_token="adm",
        stripe_webhook_secret="",
        grace_days=3,
        default_device_limit=3,
        default_runs_per_period=5,
    )
    app = create_app(settings)
    with app.state.SessionLocal() as db:
        db.add(
            License(
                license_key="TIA-TESTKEY-00000000-11111111",
                email="user@example.com",
                subscription_status="active",
                runs_quota=5,
                device_limit=3,
                created_at=utcnow(),
            )
        )
        db.commit()

    srv = _ServerThread(app, port)
    srv.start()
    atexit.register(srv.stop)
    return {"url": f"http://127.0.0.1:{port}", "app": app, "settings": settings}


@pytest.fixture
def store(tmp_path):
    return LicenseStore(path=tmp_path / "license.json")


@pytest.fixture
def client(server, store):
    return LicenseClient(
        server_url=server["url"],
        store=store,
        fingerprint="test-device-fingerprint-1",
    )


def test_fresh_machine_activation(client):
    """AC (L1): activation works on a fresh machine."""
    state = client.activate("TIA-TESTKEY-00000000-11111111")
    assert state.activation_token
    assert state.subscription_status == "active"
    assert state.quota_remaining == 5
    assert state.last_validated is not None


def test_daily_validation_uses_cache_within_24h(client):
    client.activate("TIA-TESTKEY-00000000-11111111")
    first = client.ensure_valid()
    # second call within 24h must be served from cache (no server round trip needed)
    client._get = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not hit server"))
    state = client.ensure_valid()
    assert state.activation_token == first.activation_token


def test_validation_refresh_after_24h(client, server):
    client.activate("TIA-TESTKEY-00000000-11111111")
    future = client.now + timedelta(hours=25)
    client._now = future
    state = client.ensure_valid()
    assert state.last_validated is not None


def test_record_run_decrements_quota(client):
    client.activate("TIA-TESTKEY-00000000-11111111")
    state = client.record_run("run-0001-aaaa", metadata={"repo_hash": "x", "source_code": "leak"})
    assert state.quota_remaining == 4
    # D12: metadata allowlist applied server-side; client state only holds counts


def test_offline_grace_within_3_days(client):
    """AC (L1): 3-day offline grace when server unreachable."""
    client.activate("TIA-TESTKEY-00000000-11111111")
    client.ensure_valid()

    # Simulate unreachable server by pointing at a dead port
    dead = LicenseClient(
        server_url="http://127.0.0.1:9",
        store=client.store,
        fingerprint="test-device-fingerprint-1",
        now=client.now + timedelta(days=2),
    )
    state = dead.ensure_valid()  # within grace: cached state returned
    assert state.activation_token


def test_offline_grace_exceeded_blocks(client):
    """AC (L1): block when offline beyond 3-day grace."""
    client.activate("TIA-TESTKEY-00000000-11111111")
    client.ensure_valid()

    dead = LicenseClient(
        server_url="http://127.0.0.1:9",
        store=client.store,
        fingerprint="test-device-fingerprint-1",
        now=client.now + timedelta(days=4),
    )
    with pytest.raises(LicenseBlocked) as exc:
        dead.ensure_valid()
    assert exc.value.status == "offline_grace_exceeded"


def test_expired_subscription_blocks_via_server(server, store, tmp_path):
    """AC (L1): block when subscription expired beyond grace (server decision)."""
    # App 2: license whose period ended 4 days ago (grace = 3 days)
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/expired.db",
        admin_token="adm",
        stripe_webhook_secret="",
        grace_days=3,
        default_device_limit=3,
        default_runs_per_period=5,
    )
    app = create_app(settings)
    expired_end = datetime.now(timezone.utc) - timedelta(days=4)
    with app.state.SessionLocal() as db:
        db.add(
            License(
                license_key="TIA-EXPIRED-00000000-22222222",
                subscription_status="active",
                runs_quota=5,
                device_limit=3,
                current_period_end=expired_end,
                created_at=utcnow(),
            )
        )
        db.commit()

    srv = _ServerThread(app, port)
    srv.start()
    atexit.register(srv.stop)

    expired_client = LicenseClient(
        server_url=f"http://127.0.0.1:{port}",
        store=LicenseStore(path=tmp_path / "expired_license.json"),
        fingerprint="expired-device-1",
    )
    with pytest.raises(LicenseBlocked) as exc:
        expired_client.activate("TIA-EXPIRED-00000000-22222222")
    assert "renew" in str(exc.value).lower()


def test_not_activated_blocks(client):
    with pytest.raises(LicenseBlocked) as exc:
        client.ensure_valid()
    assert exc.value.status == "not_activated"


def _isolated_server(tmp_path, db_name, license_key, quota, period_end=None):
    """Spin up a dedicated license server with one license (avoids shared-state flakiness)."""
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/{db_name}.db",
        admin_token="adm",
        stripe_webhook_secret="",
        grace_days=3,
        default_device_limit=3,
        default_runs_per_period=quota,
    )
    app = create_app(settings)
    with app.state.SessionLocal() as db:
        db.add(
            License(
                license_key=license_key,
                email="iso@example.com",
                subscription_status="active",
                runs_quota=quota,
                device_limit=3,
                current_period_end=period_end,
                created_at=utcnow(),
            )
        )
        db.commit()

    srv = _ServerThread(app, port)
    srv.start()
    atexit.register(srv.stop)
    return f"http://127.0.0.1:{port}"


def test_quota_exhausted_blocks_at_gate_before_any_work(tmp_path):
    """AC (L2): exhausted quota blocks at ensure_valid — before analysis runs."""
    url = _isolated_server(tmp_path, "quota", "TIA-QUOTA-00000000-33333333", quota=2)
    c = LicenseClient(
        server_url=url,
        store=LicenseStore(path=tmp_path / "quota_license.json"),
        fingerprint="quota-device-1",
    )
    c.activate("TIA-QUOTA-00000000-33333333")
    c.record_run("run-q-0001", metadata={})
    c.record_run("run-q-0002", metadata={})

    with pytest.raises(LicenseBlocked) as exc:
        c.ensure_valid()
    assert exc.value.status == "quota_exceeded"
    assert "quota" in str(exc.value).lower()


def test_cached_zero_quota_does_not_block_after_renewal(tmp_path):
    """Server truth wins: cached 0 + renewed subscription -> allow."""
    url = _isolated_server(tmp_path, "renew", "TIA-RENEW-00000000-44444444", quota=5)
    c = LicenseClient(
        server_url=url,
        store=LicenseStore(path=tmp_path / "renew_license.json"),
        fingerprint="renew-device-1",
    )
    c.activate("TIA-RENEW-00000000-44444444")
    # Stale local record of 0 (e.g. quota reset after renewal).
    state = c.store.load()
    state.quota_remaining = 0
    c.store.save(state)

    fresh = c.ensure_valid()  # forces refresh (quota <= 0), server returns 5
    assert fresh.quota_remaining == 5
