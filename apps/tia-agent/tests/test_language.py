"""E3/T3: language/testbed detection from a checkout or changed files."""

import json

from tia_agent.tools.language import (
    JAVASCRIPT,
    PLAYWRIGHT,
    PYTHON,
    TYPESCRIPT,
    UNKNOWN,
    detect_language_from_files,
    detect_language_from_repo,
)


def _write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _package_json(tmp_path, deps=None, dev=None):
    _write(tmp_path / "package.json", json.dumps({
        "dependencies": deps or {},
        "devDependencies": dev or {},
    }))


def test_playwright_repo(tmp_path):
    _package_json(tmp_path, dev={"@playwright/test": "^1.40.0"})
    _write(tmp_path / "tests" / "home.spec.ts", "test('x', () => {})")
    info = detect_language_from_repo(str(tmp_path))
    assert info.language == PLAYWRIGHT
    assert info.confidence == "high"
    assert info.instrumentation_language == "playwright"


def test_typescript_repo(tmp_path):
    _package_json(tmp_path)
    _write(tmp_path / "tsconfig.json", "{}")
    _write(tmp_path / "src" / "cart.ts", "export const x = 1")
    info = detect_language_from_repo(str(tmp_path))
    assert info.language == TYPESCRIPT
    assert info.instrumentation_language == "typescript"


def test_javascript_repo(tmp_path):
    _package_json(tmp_path)
    _write(tmp_path / "src" / "index.js", "module.exports = {}")
    info = detect_language_from_repo(str(tmp_path))
    assert info.language == JAVASCRIPT
    assert info.instrumentation_language == "typescript"


def test_python_repo(tmp_path):
    _write(tmp_path / "pyproject.toml", "[project]\nname='x'")
    _write(tmp_path / "src" / "x" / "mod.py", "def f():\n    return 1\n")
    info = detect_language_from_repo(str(tmp_path))
    assert info.language == PYTHON
    assert info.instrumentation_language == "python"


def test_missing_path_is_unknown(tmp_path):
    info = detect_language_from_repo(str(tmp_path / "nope"))
    assert info.language == UNKNOWN
    assert info.instrumentation_language is None


def test_detect_from_files_python_majority():
    files = ["a.py", "b.py", "c.py", "d.js"]
    info = detect_language_from_files(files)
    assert info.language == PYTHON
    assert info.confidence == "high"


def test_detect_from_files_playwright_specs():
    files = ["tests/home.spec.ts", "tests/login.spec.ts", "src/page.ts"]
    info = detect_language_from_files(files)
    assert info.language == PLAYWRIGHT
    assert info.instrumentation_language == "playwright"


def test_detect_from_files_typescript():
    files = ["src/cart.ts", "src/pricing.ts"]
    assert detect_language_from_files(files).language == TYPESCRIPT


def test_detect_from_files_empty_is_unknown():
    info = detect_language_from_files([])
    assert info.language == UNKNOWN
    assert info.to_dict()["language"] == UNKNOWN


def test_playwright_in_workspace_subpackage(tmp_path):
    _package_json(tmp_path)  # monorepo root has no playwright
    _write(tmp_path / "artifacts" / "e2e-tests" / "package.json",
           json.dumps({"devDependencies": {"@playwright/test": "^1.40.0"}}))
    _write(tmp_path / "artifacts" / "e2e-tests" / "session.spec.ts", "test('x', () => {})")
    info = detect_language_from_repo(str(tmp_path))
    assert info.language == PLAYWRIGHT
    assert info.instrumentation_language == "playwright"


def test_playwright_config_file(tmp_path):
    _package_json(tmp_path)
    _write(tmp_path / "playwright.config.ts", "export default {}")
    assert detect_language_from_repo(str(tmp_path)).language == PLAYWRIGHT


def test_skips_dependency_dirs(tmp_path):
    _package_json(tmp_path)
    _write(tmp_path / "node_modules" / "junk" / "x.ts", "export {}")
    _write(tmp_path / "src" / "real.py", "x = 1")
    info = detect_language_from_repo(str(tmp_path))
    assert info.language == JAVASCRIPT  # package.json wins, node_modules ignored
