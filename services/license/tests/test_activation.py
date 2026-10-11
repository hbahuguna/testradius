def test_fresh_machine_activation(client, license_key):
    """AC (L1): Activate on a fresh machine."""
    resp = client.post(
        "/v1/activations",
        json={"license_key": license_key, "device_fingerprint": "device-abc-12345"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["activation_token"]
    assert data["subscription_status"] == "active"
    assert data["quota_remaining"] == 5
    assert data["device_limit"] == 3


def test_activation_unknown_license(client):
    resp = client.post(
        "/v1/activations",
        json={"license_key": "TIA-00000000-00000000-00000000", "device_fingerprint": "device-abc-12345"},
    )
    assert resp.status_code == 404


def test_activation_same_device_reuses_slot(client, license_key):
    body = {"license_key": license_key, "device_fingerprint": "device-abc-12345"}
    first = client.post("/v1/activations", json=body).json()
    second = client.post("/v1/activations", json=body).json()
    assert first["activation_token"] != second["activation_token"]
    # re-activation rotates the token (old one must stop working)
    resp = client.get("/v1/validate", headers={"Authorization": f"Bearer {first['activation_token']}"})
    assert resp.status_code == 401


def test_device_limit_blocks_new_device(client, license_key):
    for i in range(3):
        resp = client.post(
            "/v1/activations",
            json={"license_key": license_key, "device_fingerprint": f"device-{i}"},
        )
        assert resp.status_code == 200
    resp = client.post(
        "/v1/activations",
        json={"license_key": license_key, "device_fingerprint": "device-4"},
    )
    assert resp.status_code == 404


def test_validate_with_token(client, license_key):
    token = client.post(
        "/v1/activations",
        json={"license_key": license_key, "device_fingerprint": "device-abc-12345"},
    ).json()["activation_token"]
    resp = client.get("/v1/validate", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["subscription_status"] == "active"
    assert data["quota_remaining"] == 5


def test_validate_rejects_bad_token(client):
    resp = client.get("/v1/validate", headers={"Authorization": "Bearer bogus"})
    assert resp.status_code == 401
