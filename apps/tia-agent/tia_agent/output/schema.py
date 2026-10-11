"""The TIA result contract (E5/O1) + a dependency-free validator.

``TiaResult.to_dict()`` must satisfy ``OUTPUT_SCHEMA``. ``validate_output`` is
hand-rolled (no ``jsonschema`` dependency) so the artifact stays stdlib+httpx on
a clean machine; the CLI validates before emitting ``--json``.
"""

from __future__ import annotations

from typing import Any, Dict, List

SCHEMA_VERSION = "1.0"

CONFIDENCE_VALUES = ("high", "medium", "low")
LANGUAGE_VALUES = (
    "python", "typescript", "javascript", "playwright",
    "java", "go", "ruby", "rust", "csharp", "php", "kotlin", "swift", "unknown",
)
TEST_REQUIRED_KEYS = ("file", "name", "nodeid", "language", "reason")

# Descriptive JSON-Schema-shaped contract (documentation + test cross-check).
OUTPUT_SCHEMA: Dict[str, Any] = {
    "title": "tia-agent result",
    "version": SCHEMA_VERSION,
    "type": "object",
    "required": [
        "schema_version", "repo", "pr_number", "files_analyzed", "changed_files",
        "symbols_selected", "tests_selected", "total_affected_tests",
        "total_tests_in_repo", "fallback_used", "fallback_reason", "confidence",
        "safety_flag", "impacted_ratio", "tests", "run_commands", "tia_run_id", "notes",
    ],
    "properties": {
        "schema_version": {"type": "string"},
        "repo": {"type": "string", "minLength": 1},
        "pr_number": {"type": "integer", "minimum": 0},
        "files_analyzed": {"type": "integer", "minimum": 0},
        "changed_files": {"type": "array", "items": {"type": "string"}},
        "symbols_selected": {"type": "integer", "minimum": 0},
        "tests_selected": {"type": "integer", "minimum": 0},
        "total_affected_tests": {"type": "integer", "minimum": 0},
        "total_tests_in_repo": {"type": ["integer", "null"], "minimum": 0},
        "fallback_used": {"type": "boolean"},
        "fallback_reason": {"type": ["string", "null"]},
        "confidence": {"type": "string", "enum": list(CONFIDENCE_VALUES)},
        "safety_flag": {"type": "boolean"},
        "impacted_ratio": {"type": ["number", "null"], "minimum": 0.0, "maximum": 1.0},
        "tests": {
            "type": "array",
            "items": {
                "type": "object",
                "required": list(TEST_REQUIRED_KEYS),
                "properties": {
                    "file": {"type": "string"},
                    "name": {"type": "string"},
                    "nodeid": {"type": "string"},
                    "language": {"type": "string", "enum": list(LANGUAGE_VALUES)},
                    "reason": {"type": "string"},
                },
            },
        },
        "run_commands": {"type": "array", "items": {"type": "string"}},
        "tia_run_id": {"type": "string"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


class OutputSchemaError(ValueError):
    """Raised by ``require_valid_output`` when a result violates the contract."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("invalid TIA output: " + "; ".join(errors))


def validate_output(data: Dict[str, Any]) -> List[str]:
    """Return a list of human-readable problems ([] when the data is valid)."""
    errors: List[str] = []

    def _is_int(v: Any) -> bool:
        return isinstance(v, int) and not isinstance(v, bool)

    required = OUTPUT_SCHEMA["required"]
    for key in required:
        if key not in data:
            errors.append(f"missing required field '{key}'")
    for key in data:
        if key not in OUTPUT_SCHEMA["properties"]:
            errors.append(f"unknown field '{key}'")

    if "schema_version" in data and not isinstance(data["schema_version"], str):
        errors.append("schema_version must be a string")
    if not isinstance(data.get("repo"), str) or not data.get("repo"):
        errors.append("repo must be a non-empty string")
    for key in ("pr_number", "files_analyzed", "symbols_selected",
                "tests_selected", "total_affected_tests"):
        if key in data and (not _is_int(data[key]) or data[key] < 0):
            errors.append(f"{key} must be a non-negative integer")
    if not isinstance(data.get("changed_files"), list) or \
            not all(isinstance(x, str) for x in data.get("changed_files", [])):
        errors.append("changed_files must be a list of strings")
    ttir = data.get("total_tests_in_repo")
    if ttir is not None and (not _is_int(ttir) or ttir < 0):
        errors.append("total_tests_in_repo must be null or a non-negative integer")
    if not isinstance(data.get("fallback_used"), bool):
        errors.append("fallback_used must be a boolean")
    if data.get("fallback_reason") is not None and not isinstance(data["fallback_reason"], str):
        errors.append("fallback_reason must be null or a string")
    if data.get("confidence") not in CONFIDENCE_VALUES:
        errors.append(f"confidence must be one of {CONFIDENCE_VALUES}")
    if not isinstance(data.get("safety_flag"), bool):
        errors.append("safety_flag must be a boolean")
    ratio = data.get("impacted_ratio")
    if ratio is not None and (not isinstance(ratio, (int, float)) or isinstance(ratio, bool)
                              or not (0.0 <= ratio <= 1.0)):
        errors.append("impacted_ratio must be null or a number in [0, 1]")
    if not isinstance(data.get("run_commands"), list) or \
            not all(isinstance(x, str) for x in data.get("run_commands", [])):
        errors.append("run_commands must be a list of strings")
    if not isinstance(data.get("tia_run_id"), str) or not data.get("tia_run_id"):
        errors.append("tia_run_id must be a non-empty string")
    if not isinstance(data.get("notes"), list) or \
            not all(isinstance(x, str) for x in data.get("notes", [])):
        errors.append("notes must be a list of strings")

    tests = data.get("tests")
    if not isinstance(tests, list):
        errors.append("tests must be a list")
    else:
        for i, t in enumerate(tests):
            if not isinstance(t, dict):
                errors.append(f"tests[{i}] must be an object")
                continue
            for key in TEST_REQUIRED_KEYS:
                if key not in t:
                    errors.append(f"tests[{i}] missing '{key}'")
            if t.get("language") not in LANGUAGE_VALUES:
                errors.append(f"tests[{i}].language invalid: {t.get('language')!r}")
    return errors


def require_valid_output(data: Dict[str, Any]) -> Dict[str, Any]:
    errors = validate_output(data)
    if errors:
        raise OutputSchemaError(errors)
    return data
