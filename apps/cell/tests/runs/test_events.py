import asyncio
import json
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from jsonschema import Draft202012Validator, FormatChecker

from cell import main

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[4] / "packages/shared-types/contracts/run-event.v1.json"
    ).read_text()
)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def test_sse_events_are_ordered_and_match_the_contract():
    async def scenario():
        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/runs",
                json={"repo": "fixture", "commit": "abc1234", "scope": "full", "policy": {}},
            )
            data = response.json()
            stream = await client.get(
                f"/v1/runs/{data['run_id']}/events",
                headers={"Authorization": f"Bearer {data['run_token']}"},
            )
            assert stream.status_code == 200
            return stream.text

    text = asyncio.run(scenario())

    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            event = json.loads(line[6:])
            VALIDATOR.validate(event)
            events.append(event)

    assert events
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert any(event["payload"].get("event") == "run.completed" for event in events)


def test_sse_requires_the_run_token():
    from fastapi.testclient import TestClient

    client = TestClient(main.app)
    response = client.post(
        "/v1/runs",
        json={"repo": "fixture", "commit": "abc1234", "scope": "full", "policy": {}},
    )
    run_id = response.json()["run_id"]

    stream = client.get(f"/v1/runs/{run_id}/events")

    assert stream.status_code == 401
