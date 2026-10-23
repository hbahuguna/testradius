"""The cell must never contain UI code, static assets, or a UI framework.

The checks are pure functions so `test_rule_engine.py` can prove that a synthetic
violation is caught and reported with the offending name and rule (E0-S7 AC2).
"""

from __future__ import annotations

import ast
import json
import tomllib
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CELL = ROOT / "apps" / "cell"
RULES = tomllib.loads((Path(__file__).parent / "rules.toml").read_text())["cell"]

ALLOW = set(RULES["allow_path_parts"])


def _allowed(path: Path) -> bool:
    return any(part in ALLOW for part in path.parts)


def _python_files() -> list[Path]:
    return [path for path in (CELL / "cell").rglob("*.py") if not _allowed(path)]


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def _matches(module: str, denied: str) -> bool:
    return module == denied or module.startswith(f"{denied}.")


def _normalize_dependency(spec: str) -> str:
    return spec.split(">=")[0].split("==")[0].split("[")[0].strip().lower()


def import_violations(modules: Iterable[str], denied: Iterable[str]) -> list[str]:
    violations: list[str] = []
    for module in sorted(set(modules)):
        for denied_module in denied:
            if _matches(module, denied_module):
                violations.append(
                    f"rule=deny_python_imports matched '{module}' "
                    f"(denied prefix '{denied_module}')"
                )
    return violations


def dependency_violations(
    dependencies: Iterable[str], denied: Iterable[str], rule: str
) -> list[str]:
    denied_set = {name.lower() for name in denied}
    violations: list[str] = []
    for spec in sorted(set(dependencies)):
        if _normalize_dependency(spec) in denied_set:
            violations.append(f"rule={rule} matched dependency '{spec}'")
    return violations


def node_manifest_violations(manifest: Path, denied: Iterable[str]) -> list[str]:
    data = json.loads(manifest.read_text())
    names = set(data.get("dependencies", {})) | set(data.get("devDependencies", {}))
    return dependency_violations(names, denied, "deny_node_dependencies")


def filesystem_violations(
    root: Path,
    denied_dirs: Iterable[str],
    denied_suffixes: Iterable[str],
    allowed_parts: Iterable[str],
) -> list[str]:
    denied_dir_set = set(denied_dirs)
    denied_suffix_set = {suffix.lower() for suffix in denied_suffixes}
    allow = set(allowed_parts)
    violations: list[str] = []

    for path in root.rglob("*"):
        if any(part in allow for part in path.parts):
            continue
        relative = path.relative_to(root)
        if path.is_dir() and path.name in denied_dir_set:
            violations.append(
                f"rule=deny_directory_names matched directory '{relative}' "
                f"(denied name '{path.name}')"
            )
        if path.is_file() and path.suffix.lower() in denied_suffix_set:
            violations.append(
                f"rule=deny_file_extensions matched file '{relative}' "
                f"(denied extension '{path.suffix}')"
            )
    return violations


def test_cell_imports_no_ui_or_template_modules() -> None:
    violations: list[str] = []
    for path in _python_files():
        for violation in import_violations(
            _imported_modules(path), RULES["deny_python_imports"]
        ):
            violations.append(f"{path.relative_to(ROOT)}: {violation}")

    assert not violations, "UI/template imports in the cell:\n" + "\n".join(violations)


def test_cell_pyproject_declares_no_ui_dependencies() -> None:
    pyproject = tomllib.loads((CELL / "pyproject.toml").read_text())
    dependencies = pyproject["project"]["dependencies"]

    violations = dependency_violations(
        dependencies, RULES["deny_python_dependencies"], "deny_python_dependencies"
    )

    assert not violations, "denied dependencies in cell pyproject:\n" + "\n".join(
        violations
    )


def test_cell_node_manifest_has_no_ui_dependencies() -> None:
    manifest = CELL / "package.json"
    if not manifest.exists():
        return

    violations = node_manifest_violations(manifest, RULES["deny_node_dependencies"])

    assert not violations, "denied node dependencies in the cell:\n" + "\n".join(
        violations
    )


def test_cell_serves_no_static_or_template_files() -> None:
    violations = filesystem_violations(
        CELL,
        RULES["deny_directory_names"],
        RULES["deny_file_extensions"],
        ALLOW,
    )

    assert not violations, "static assets in the cell:\n" + "\n".join(violations)
