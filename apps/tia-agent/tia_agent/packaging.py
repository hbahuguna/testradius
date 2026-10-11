"""PyInstaller packaging metadata (E6/R1) — single source of truth.

The ``tia-agent.spec`` build definition and ``tests/test_packaging.py`` both read
from here, so the frozen binary and its verification can't drift:

* :func:`hidden_imports` — every ``tia_agent`` / ``license_client`` module plus a
  few third-party extras, discovered from disk (no hand-maintained list to forget).
* :data:`ENTRY_SCRIPT`, :data:`BINARY_NAME` — entry point + artifact name.
* :data:`EXCLUDES` — heavyweight stdlib/third-party packages not used by the agent.

Nothing in the agent reads files relative to its package, so no ``datas`` are
required: the backend ``docker-compose.yml`` is *rendered at runtime*
(:mod:`tia_agent.backend.compose`), which is what keeps R1's "compose bundled"
true inside a one-file executable.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import List

#: Frozen entry point (absolute imports; see pyi_entry.py for why not __main__.py).
ENTRY_SCRIPT = "pyi_entry.py"
BINARY_NAME = "tia-agent"

#: Packages whose modules must be bundled explicitly.
BUNDLED_PACKAGES = ("tia_agent", "license_client")

#: Third-party/entropy sources PyInstaller may not infer from static analysis.
EXTRA_HIDDEN_IMPORTS = (
    "httpx",
    "httpcore",
    "h11",
    "anyio",
    "sniffio",
    "certifi",
    "idna",
)

#: Keep the artifact small — none of these are imported by the agent.
EXCLUDES = (
    "tkinter",
    "PIL",
    "numpy",
    "pandas",
    "matplotlib",
    "scipy",
    "pytest",
    "IPython",
    "setuptools",
    "pip",
    "wheel",
)


def _package_root(package: str) -> Path:
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        raise ImportError(f"cannot locate package '{package}'")
    return Path(next(iter(spec.submodule_search_locations)))


def discover_modules(package: str) -> List[str]:
    """All importable module names under ``package`` (from the filesystem)."""
    root = _package_root(package)
    names = {package}
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(root)
        if rel.name == "__init__.py":
            dotted = ".".join((package, *rel.parts[:-1]))
        else:
            dotted = ".".join((package, *rel.parts))[: -len(".py")]
        names.add(dotted)
    return sorted(names)


def _importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def hidden_imports() -> List[str]:
    """Complete hidden-import list for the PyInstaller spec.

    Third-party extras are kept only when actually importable, so the list is
    valid whether or not optional transitive deps (e.g. ``sniffio`` on newer
    ``anyio``) are present in the build environment.
    """
    modules: set = {name for name in EXTRA_HIDDEN_IMPORTS if _importable(name)}
    for package in BUNDLED_PACKAGES:
        modules.update(discover_modules(package))
    return sorted(modules)


def required_imports() -> List[str]:
    """Modules the build must include for the package to run (test invariant)."""
    modules: set = set()
    for package in BUNDLED_PACKAGES:
        modules.update(discover_modules(package))
    return sorted(modules)
