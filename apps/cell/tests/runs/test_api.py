from fastapi.testclient import TestClient

from cell import main


def make_client():
    return TestClient(main.app)


def test_create_run_returns_token():
    c = make_client()
    r = c.post(
        "/v1/runs",
        json={
            "repo": "fixture",
            "commit": "abc1234",
            "scope": "full",
            "policy": {"allow_network": False},
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert "run_id" in data and "run_token" in data


def test_get_run_requires_auth():
    c = make_client()
    r = c.post(
        "/v1/runs", json={"repo": "fixture", "commit": "abc1234", "scope": "full", "policy": {}}
    )
    run_id = r.json()["run_id"]
    resp = c.get(f"/v1/runs/{run_id}")
    assert resp.status_code == 401


def test_get_run_and_cancel():
    c = make_client()
    r = c.post(
        "/v1/runs", json={"repo": "fixture", "commit": "abc1234", "scope": "full", "policy": {}}
    )
    data = r.json()
    run_id = data["run_id"]
    token = data["run_token"]
    headers = {"Authorization": f"Bearer {token}"}
    g = c.get(f"/v1/runs/{run_id}", headers=headers)
    assert g.status_code == 200
    x = c.post(f"/v1/runs/{run_id}/cancel", headers=headers)
    assert x.status_code == 200


def test_evidence_empty():
    c = make_client()
    r = c.post(
        "/v1/runs", json={"repo": "fixture", "commit": "abc1234", "scope": "full", "policy": {}}
    )
    data = r.json()
    resp = c.get(
        f"/v1/runs/{data['run_id']}/evidence",
        headers={"Authorization": f"Bearer {data['run_token']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["evidence"] == []


def test_policy_reload():
    c = make_client()
    resp = c.post("/v1/policy/reload")
    assert resp.status_code == 200
