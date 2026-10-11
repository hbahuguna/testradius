"""E6/R1: binary packaging invariants + frozen-binary smoke test."""

import subprocess
import sys
from pathlib import Path

import pytest

from tia_agent import packaging
from tia_agent.packaging import (
    BINARY_NAME,
    BUNDLED_PACKAGES,
    ENTRY_SCRIPT,
    discover_modules,
    hidden_imports,
    required_imports,
)

APP_DIR = Path(__file__).resolve().parents[1]
SPEC = APP_DIR / "tia-agent.spec"
BUILD_SCRIPT = APP_DIR / "scripts" / "build_binary.sh"
FROZEN_BINARY = APP_DIR / "dist" / BINARY_NAME


# ---------------------------------------------------------------------------
# spec + build assets
# ---------------------------------------------------------------------------

def test_spec_and_build_script_exist():
    assert SPEC.is_file()
    assert BUILD_SCRIPT.is_file()
    assert BUILD_SCRIPT.stat().st_mode & 0o111, "build script should be executable"


def test_spec_uses_packaging_metadata():
    text = SPEC.read_text()
    assert ENTRY_SCRIPT in text or "ENTRY_SCRIPT" in text
    assert "hidden_imports()" in text          # single source of truth
    assert "EXCLUDES" in text
    assert "EXE(" in text and "PYZ" in text     # one-file build
    assert "COLLECT(" not in text               # one-file, not one-dir


def test_pyproject_declares_binary_entry_and_build_extra():
    text = (APP_DIR / "pyproject.toml").read_text()
    assert "tia-agent = \"tia_agent.interfaces.cli:main\"" in text
    assert "build = [" in text and "pyinstaller" in text


# ---------------------------------------------------------------------------
# hidden-import completeness
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("package", BUNDLED_PACKAGES)
def test_discover_covers_every_source_file(package):
    root = packaging._package_root(package)
    expected = set()
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        parts = p.relative_to(root).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        expected.add(".".join((package, *parts)))
    # Exact match: no source file can be silently omitted from the bundle.
    assert expected == set(discover_modules(package))


def test_hidden_imports_include_all_agent_and_license_modules():
    listed = set(hidden_imports())
    assert set(required_imports()) <= listed
    for must in ("tia_agent", "tia_agent.interfaces.cli", "tia_agent.backend.compose",
                 "tia_agent.privacy", "tia_agent.output.schema",
                 "license_client", "license_client.store"):
        assert must in listed, f"{must} missing from hidden imports"
    assert "httpx" in listed


def test_no_package_relative_resource_reads():
    """PyInstaller one-file only bundles what we declare; nothing may read
    files relative to its own package (no datas are declared)."""
    root = packaging._package_root("tia_agent")
    offenders = []
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if "__file__" in path.read_text():
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], f"package-relative reads need bundling: {offenders}"


# ---------------------------------------------------------------------------
# entry point works (same entry the frozen binary uses)
# ---------------------------------------------------------------------------

def test_module_entry_point_version():
    proc = subprocess.run(
        [sys.executable, "-m", "tia_agent", "--version"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "tia-agent" in proc.stdout


def test_module_entry_point_help():
    proc = subprocess.run(
        [sys.executable, "-m", "tia_agent", "--help"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "analyze" in proc.stdout


# ---------------------------------------------------------------------------
# frozen binary (only when built)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not FROZEN_BINARY.exists(), reason="binary not built (run scripts/build_binary.sh)")
def test_frozen_binary_runs_on_stripped_env():
    # A deliberately minimal environment to approximate a clean machine.
    proc = subprocess.run(
        [str(FROZEN_BINARY), "--version"],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home())},
    )
    assert proc.returncode == 0
    assert "tia-agent" in proc.stdout


@pytest.mark.skipif(not FROZEN_BINARY.exists(), reason="binary not built")
def test_frozen_binary_help_and_no_python_on_path():
    proc = subprocess.run(
        [str(FROZEN_BINARY), "--help"],
        capture_output=True, text=True,
        env={"PATH": "/nonexistent", "HOME": str(Path.home())},
    )
    assert proc.returncode == 0
    assert "usage" in proc.stdout.lower()
