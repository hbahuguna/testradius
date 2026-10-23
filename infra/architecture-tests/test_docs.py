"""Documentation gates: every ADR follows the decision template (E0-S4 AC1)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADR_DIR = ROOT / "docs" / "adr"

REQUIRED_SECTIONS = [
    "## Context",
    "## Decision",
    "## Consequences",
    "## Alternatives considered",
]


def adr_files() -> list[Path]:
    return sorted(
        path for path in ADR_DIR.glob("*.md") if re.match(r"^\d{3}-", path.name)
    )


def test_at_least_seven_adrs_exist() -> None:
    assert len(adr_files()) >= 7


def test_every_adr_follows_the_template() -> None:
    problems: list[str] = []
    for path in adr_files():
        text = path.read_text()
        missing = [section for section in REQUIRED_SECTIONS if section not in text]
        if missing:
            problems.append(f"{path.name}: missing {', '.join(missing)}")

    assert not problems, "ADR template violations:\n" + "\n".join(problems)


def test_adr_numbers_are_unique() -> None:
    numbers = [path.name.split("-", 1)[0] for path in adr_files()]

    assert len(numbers) == len(set(numbers))


def test_sprint_and_runbook_docs_exist() -> None:
    for relative in (
        "docs/sprints/sprint-1-plan.md",
        "docs/demos/sprint-1.md",
        "docs/runbooks/local-dev.md",
        "docs/architecture-tests.md",
    ):
        assert (ROOT / relative).exists(), f"missing {relative}"
