from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from cell.agent.types import StepResult


def test_step_payload_matches_the_shared_schema():
    schema = json.loads(
        (
            Path(__file__).resolve().parents[4]
            / "packages/shared-types/contracts/agent-step.v1.json"
        ).read_text()
    )
    payload = StepResult(
        step_id="s1",
        intent="open the page",
        ok=True,
        verdict="passed",
        detail="ok",
        citations=["file:public/index.html"],
        action="browser.navigate",
        arguments={"url": "http://mock-aut:8080/"},
        observation="ok",
        duration_ms=12,
    ).to_dict()

    Draft202012Validator(schema).validate(payload)
    assert payload["thought"] == "open the page"
    assert payload["schema_version"] == "1"
    assert payload["duration_ms"] == 12
