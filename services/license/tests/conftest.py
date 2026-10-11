import os

import pytest
from fastapi.testclient import TestClient

from license_server.app import create_app
from license_server.config import Settings
from license_server.models import Base, License, utcnow


@pytest.fixture
def settings(tmp_path):
    return Settings(
        database_url=f"sqlite:///{tmp_path}/license_test.db",
        admin_token="test-admin-token",
        stripe_webhook_secret="",
        grace_days=3,
        default_device_limit=3,
        default_runs_per_period=5,
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def license_key(app):
    from license_server.models import generate_license_key

    key = generate_license_key()
    with app.state.SessionLocal() as db:
        db.add(
            License(
                license_key=key,
                email="user@example.com",
                subscription_status="active",
                runs_quota=5,
                device_limit=3,
                created_at=utcnow(),
            )
        )
        db.commit()
    return key
