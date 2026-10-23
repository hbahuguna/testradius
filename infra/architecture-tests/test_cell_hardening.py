"""Objective checks for the cell's hardening claims (E1-S1, ADR-001, ADR-002)."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "apps" / "cell" / "Dockerfile"
COMPOSE = ROOT / "infra" / "compose" / "compose.factory.yaml"


def dockerfile_lines() -> list[str]:
    return DOCKERFILE.read_text().splitlines()


def test_image_is_python_312() -> None:
    assert any(
        line.strip() == "FROM python:3.12-slim-bookworm" for line in dockerfile_lines()
    )


def test_image_runs_as_uid_10001() -> None:
    users = [
        line.split(maxsplit=1)[1]
        for line in dockerfile_lines()
        if line.strip().upper().startswith("USER ")
    ]

    assert users, "Dockerfile must set USER"
    assert users[-1].strip() == "10001", f"final USER must be 10001, got {users[-1]!r}"


def test_image_installs_chromium_only() -> None:
    text = DOCKERFILE.read_text()

    assert "playwright install --with-deps chromium" in text
    assert "--with-deps firefox" not in text
    assert "--with-deps webkit" not in text


def test_image_never_references_a_docker_socket() -> None:
    assert "docker.sock" not in DOCKERFILE.read_text()


def test_image_uses_no_privileged_mode() -> None:
    text = DOCKERFILE.read_text().lower()

    assert "privileged" not in text
    assert "cap_sys_admin" not in text


def compose_cell() -> dict:
    data = yaml.safe_load(COMPOSE.read_text())
    return data["services"]["cell"]


def test_compose_runs_cell_read_only() -> None:
    assert compose_cell()["read_only"] is True


def test_compose_drops_all_capabilities() -> None:
    assert "ALL" in compose_cell()["cap_drop"]


def test_compose_prevents_privilege_escalation() -> None:
    options = compose_cell()["security_opt"]
    assert any("no-new-privileges:true" in option for option in options)


def test_compose_uses_the_non_root_uid() -> None:
    assert compose_cell()["user"] == "10001:10001"


def test_compose_never_mounts_a_docker_socket() -> None:
    assert "docker.sock" not in COMPOSE.read_text()
