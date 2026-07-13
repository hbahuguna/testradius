"""Goal specification parser for agentic tests.

A goal spec expresses a test as an *objective* rather than a fixed sequence of
actions (Slack's agentic testing model: ``goal -> agent adapts -> verify
result``). Specs can be YAML or JSON with the goal, the URL under test, the
assertions to verify, optional constraints on allowed actions, and stopping
conditions (cost/turn/duration guards).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    import yaml  # type: ignore

    _HAVE_YAML = True
except Exception:  # pragma: no cover
    _HAVE_YAML = False


@dataclass
class AssertionSpec:
    type: str  # visibility | text | url
    description: str = ""
    target: str = ""
    expected: str = ""
    pattern: str = ""
    kind: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "description": self.description,
            "target": self.target,
            "expected": self.expected,
            "pattern": self.pattern,
            "kind": self.kind,
        }


@dataclass
class GoalSpec:
    goal: str
    url: str
    assertions: list[AssertionSpec] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    stopping: dict[str, Any] = field(default_factory=dict)
    backend: str = "mcp"

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "url": self.url,
            "assertions": [a.to_dict() for a in self.assertions],
            "constraints": self.constraints,
            "stopping": self.stopping,
            "backend": self.backend,
        }

    def assertion_dicts(self) -> list[dict[str, Any]]:
        return [a.to_dict() for a in self.assertions]


def parse_assertion(d: dict[str, Any]) -> AssertionSpec:
    return AssertionSpec(
        type=d.get("type", "visibility"),
        description=d.get("description", ""),
        target=d.get("target", ""),
        expected=d.get("expected", ""),
        pattern=d.get("pattern", ""),
        kind=d.get("kind", "auto"),
    )


def load_goal_spec(text: str, fmt: Optional[str] = None) -> GoalSpec:
    """Parse a goal spec from YAML or JSON text."""
    fmt = fmt or ("yaml" if (not text.strip().startswith("{") and not text.strip().startswith("[")) else "json")
    if fmt == "yaml":
        if not _HAVE_YAML:
            raise RuntimeError("PyYAML not installed; provide JSON or install pyyaml")
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)

    assertions = [parse_assertion(a) for a in data.get("assertions", [])]
    return GoalSpec(
        goal=data.get("goal", ""),
        url=data.get("url", ""),
        assertions=assertions,
        constraints=data.get("constraints", {}) or {},
        stopping=data.get("stopping_conditions", data.get("stopping", {})) or {},
        backend=data.get("backend", "mcp"),
    )


def load_goal_spec_file(path: str) -> GoalSpec:
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    fmt = "yaml" if path.endswith((".yaml", ".yml")) else "json"
    return load_goal_spec(text, fmt)
