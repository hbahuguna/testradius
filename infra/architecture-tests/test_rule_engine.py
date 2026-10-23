"""Prove the rule engine catches synthetic violations (E0-S7 AC2, E0-S3 AC2).

These tests do not depend on the real tree: they construct the violation, run the same
functions the architecture suite uses, and assert that the message names the offending
dependency/file and the rule that failed.
"""

from __future__ import annotations

from pathlib import Path

from test_no_ui_in_cell import (
    dependency_violations,
    filesystem_violations,
    import_violations,
    node_manifest_violations,
)


def test_python_import_rule_names_module_and_rule() -> None:
    violations = import_violations({"jinja2", "fastapi"}, {"jinja2"})

    assert violations == [
        "rule=deny_python_imports matched 'jinja2' (denied prefix 'jinja2')"
    ]


def test_python_import_rule_catches_a_submodule() -> None:
    violations = import_violations({"fastapi.staticfiles"}, {"fastapi.staticfiles"})

    assert violations and "fastapi.staticfiles" in violations[0]


def test_pyproject_rule_names_the_dependency() -> None:
    violations = dependency_violations(
        ["fastapi>=0.115", "Jinja2>=3.1"], {"jinja2"}, "deny_python_dependencies"
    )

    assert len(violations) == 1
    assert "Jinja2>=3.1" in violations[0]
    assert "deny_python_dependencies" in violations[0]


def test_node_rule_catches_express_in_a_cell_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "package.json"
    manifest.write_text('{"dependencies": {"express": "^4.21.0"}}')

    violations = node_manifest_violations(manifest, {"express"})

    assert len(violations) == 1
    assert "express" in violations[0]
    assert "deny_node_dependencies" in violations[0]


def test_filesystem_rule_catches_public_index_html(tmp_path: Path) -> None:
    public = tmp_path / "public"
    public.mkdir()
    (public / "index.html").write_text("<html></html>")

    violations = filesystem_violations(tmp_path, {"public"}, {".html"}, set())

    assert any(
        "deny_directory_names" in violation and "public" in violation
        for violation in violations
    )
    assert any(
        "deny_file_extensions" in violation and "index.html" in violation
        for violation in violations
    )


def test_filesystem_rule_allows_test_fixtures(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "fixture.html").write_text("")

    violations = filesystem_violations(tmp_path, {"public"}, {".html"}, {"tests"})

    assert violations == []
