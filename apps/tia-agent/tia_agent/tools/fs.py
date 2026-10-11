"""Read-only filesystem tools (E4/F1).

Two jobs, both side-effect free:

* ``validate_tests`` — existence check: drop evidence-returned test files that
  are not actually present in the user's checkout.
* ``discover_tests_fallback`` — the deterministic fallback: when the evidence
  graph yields nothing (e.g. brand-new files), list local test files so the run
  can still produce runnable commands, with ``fallback_used=true`` + reason.

Paths coming back from the backend may be absolute container paths
(``/workdir/<repo>/...`` or legacy ``/testradius/...``); these are reduced to
repo-relative paths before checking the filesystem.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .language import PYTHON, language_from_file

_PY_CASE = re.compile(r"^\s*(?:async\s+)?def\s+test\w*\s*\(", re.MULTILINE)
_JS_CASE = re.compile(r"(?:^|[^.\w])(?:it|test)(?:\.\w+)?\s*\(", re.MULTILINE)

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    "out", ".next", ".nuxt", "coverage", "htmlcov", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".tox", ".idea", ".vscode",
}

_TEST_SUFFIXES = (
    ".spec.ts", ".test.ts", ".spec.tsx", ".test.tsx",
    ".spec.js", ".test.js", ".spec.jsx", ".test.jsx",
)
_TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs"}
_CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


@dataclass
class ValidateResult:
    valid: List[Dict[str, Any]] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)

    @property
    def dropped(self) -> int:
        return len(self.missing)


def repo_relative(path: str, repo_path: Optional[str] = None) -> str:
    """Reduce a backend/absolute path to a repo-relative POSIX path."""
    if not path:
        return ""
    p = str(path).replace("\\", "/").strip()
    if repo_path:
        root = os.path.abspath(os.path.expanduser(str(repo_path))).replace("\\", "/").rstrip("/")
        if p == root:
            return ""
        if p.startswith(root + "/"):
            return p[len(root) + 1:]
    p = p.lstrip("/")
    if p.startswith("testradius/"):
        p = p[len("testradius/"):]
    elif p.startswith("workdir/"):
        parts = p.split("/")
        p = "/".join(parts[2:]) if len(parts) > 2 else ""
    while p.startswith("./"):
        p = p[2:]
    return p


def test_file_exists(path: str, repo_path: Optional[str] = None) -> bool:
    """True when ``path`` resolves to a file inside the checkout.

    Without a ``repo_path`` we cannot verify, so we assume it exists.
    """
    if not path:
        return False
    if not repo_path:
        return True
    rel = repo_relative(path, repo_path)
    if not rel:
        return False
    return (Path(repo_path) / rel).is_file()


def validate_tests(
    tests: Iterable[Dict[str, Any]],
    repo_path: Optional[str] = None,
) -> ValidateResult:
    """Split tests into those whose file exists and those that are missing."""
    if not repo_path:
        return ValidateResult(valid=list(tests), missing=[])
    valid: List[Dict[str, Any]] = []
    missing: List[str] = []
    for t in tests:
        f = t.get("file") or ""
        if not f or test_file_exists(f, repo_path):
            valid.append(t)
        else:
            missing.append(f)
    return ValidateResult(valid=valid, missing=missing)


def is_test_file(rel_path: str) -> bool:
    rel = Path(rel_path)
    name = rel.name.lower()
    if name.startswith("test_") and name.endswith(".py"):
        return True
    if name.endswith("_test.py"):
        return True
    if name.endswith(_TEST_SUFFIXES):
        return True
    if name.endswith(_CODE_SUFFIXES) and any(d in _TEST_DIRS for d in rel.parts[:-1]):
        return True
    return False


def iter_test_files(
    repo_path: str,
    language: Optional[str] = None,
    *,
    limit: int = 500,
) -> List[str]:
    """Repo-relative paths of local test files (bounded, skip-dirs pruned)."""
    root = Path(repo_path)
    if not root.is_dir():
        return []
    out: List[str] = []
    for p in root.rglob("*"):
        if len(out) >= limit:
            break
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if not is_test_file(rel.as_posix()):
            continue
        if language == PYTHON and p.suffix.lower() != ".py":
            continue
        if language in ("typescript", "playwright") and p.suffix.lower() not in (".ts", ".tsx"):
            continue
        out.append(rel.as_posix())
    return sorted(out)


def discover_tests_fallback(
    changed_files: Optional[Iterable[str]],
    repo_path: str,
    language: Optional[str] = None,
    *,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """Deterministic fallback: list local tests (related ones first)."""
    files = iter_test_files(repo_path, language, limit=limit)
    related = _related_tests(files, changed_files or [])
    chosen = related or files
    scope = "related to the changed files" if related else "the full local test suite"
    out: List[Dict[str, Any]] = []
    for f in chosen:
        out.append({
            "file": f,
            "name": "",
            "nodeid": f,
            "language": language_from_file(f),
            "reason": f"discovered locally ({scope})",
        })
    return out


def count_test_cases(repo_path: str, language: Optional[str] = None) -> int:
    """Approximate the size of the local test suite (safety-ratio denominator).

    Counts ``def test_*`` in Python test files and ``it(...)``/``test(...)`` calls
    in JS/TS test files. Falls back to the file count when no cases are found.
    """
    files = iter_test_files(repo_path, language, limit=2000)
    total = 0
    for f in files:
        p = Path(repo_path) / f
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        pattern = _PY_CASE if p.suffix.lower() == ".py" else _JS_CASE
        total += len(pattern.findall(text))
    return total or len(files)


def _related_tests(test_files: List[str], changed_files: Iterable[str]) -> List[str]:
    stems = set()
    for c in changed_files:
        stem = Path(str(c)).stem.lower()
        stems.add(_core_stem(stem))
    stems.discard("")
    if not stems:
        return []
    out = []
    for f in test_files:
        core = _core_stem(Path(f).stem.lower())
        if any(_related(core, s) for s in stems):
            out.append(f)
    return out


def _related(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    # Substring only counts when both sides are specific enough (avoid "a" in "brand_new").
    return len(a) >= 4 and len(b) >= 4 and (a in b or b in a)


def _core_stem(stem: str) -> str:
    if stem.startswith("test_"):
        stem = stem[len("test_"):]
    elif stem.endswith("_test"):
        stem = stem[: -len("_test")]
    return stem.split(".", 1)[0]
