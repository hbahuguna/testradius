from __future__ import annotations

import time

from fastapi.testclient import TestClient

from cell.config import Settings
from cell.main import create_app


def test_create_run_can_start_the_agent_runtime(tmp_path):
    (tmp_path / "index.html").write_text("<h1>Menu</h1>")
    settings = Settings(state_dir=str(tmp_path), fixture_repo_path=str(tmp_path))
    app = create_app(settings=settings)

    with TestClient(app) as client:
        response = client.post(
            "/v1/runs",
            json={
                "repo": "fixture",
                "commit": "abc1234",
                "scope": "full",
                "goal": "verify checkout",
                "policy": {
                    "runtime": "agent",
                    "provider": "fake",
                    "fake_plan": {
                        "steps": [
                            {
                                "step_id": "open",
                                "intent": "open fixture",
                                "tool": "browser.navigate",
                                "arguments": {"url": "http://aut/"},
                                "citations": ["file:index.html"],
                            }
                        ]
                    },
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        headers = {"Authorization": f"Bearer {data['run_token']}"}

        status = ""
        body = {}
        for _ in range(200):
            body = client.get(f"/v1/runs/{data['run_id']}", headers=headers).json()
            status = body["status"]
            if status in {"succeeded", "failed", "cancelled", "timed_out"}:
                break
            time.sleep(0.01)

        assert status == "succeeded", body
