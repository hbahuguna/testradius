import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from cell.models import RunEvent

SHARED_TYPES = Path(__file__).resolve().parents[3] / "packages" / "shared-types"
SCHEMA = json.loads((SHARED_TYPES / "contracts" / "run-event.v1.json").read_text())
VALID = json.loads((SHARED_TYPES / "fixtures" / "run-event.valid.json").read_text())
INVALID = json.loads((SHARED_TYPES / "fixtures" / "run-event.invalid.json").read_text())


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    return Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def test_valid_fixture_matches_the_shared_schema(validator: Draft202012Validator) -> None:
    validator.validate(VALID)


def test_invalid_fixture_is_rejected(validator: Draft202012Validator) -> None:
    with pytest.raises(ValidationError):
        validator.validate(INVALID)


def test_python_model_serializes_to_the_shared_schema(validator: Draft202012Validator) -> None:
    event = RunEvent.model_validate(VALID)

    validator.validate(event.model_dump(mode="json"))


def test_schema_version_is_pinned(validator: Draft202012Validator) -> None:
    stale = {**VALID, "schema_version": "2"}

    with pytest.raises(ValidationError):
        validator.validate(stale)
