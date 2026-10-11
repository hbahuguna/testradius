"""Detect the repo language/testbed (E3/T3 cross-repo).

TestRadius instrumentation takes a language hint (``python``, ``typescript``,
``playwright``). We infer it from a local checkout when available (preferred:
reads ``package.json`` deps) or, when only changed paths are known, from file
extensions. No side effects — pure filesystem reads.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

PYTHON = "python"
TYPESCRIPT = "typescript"
PLAYWRIGHT = "playwright"
JAVASCRIPT = "javascript"
UNKNOWN = "unknown"

# What we hand the instrumentation endpoint for each detected language.
_INSTRUMENTATION = {
    PYTHON: "python",
    TYPESCRIPT: "typescript",
    PLAYWRIGHT: "playwright",
    JAVASCRIPT: "typescript",
}

_PLAYWRIGHT_DEPS = ("@playwright/test", "playwright", "playwright-core")
# JS test runners we can emit run commands for (checked in priority order).
_JS_RUNNERS = (
    ("playwright", _PLAYWRIGHT_DEPS),
    ("vitest", ("vitest",)),
    ("jest", ("jest", "jest-cli", "@jest/core")),
)
_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    "out", ".next", "coverage", ".mypy_cache", ".pytest_cache",
}

_EXT_LANGUAGE = {
    ".py": PYTHON,
    ".ts": TYPESCRIPT, ".tsx": TYPESCRIPT,
    ".js": JAVASCRIPT, ".jsx": JAVASCRIPT, ".mjs": JAVASCRIPT, ".cjs": JAVASCRIPT,
    ".java": "java", ".go": "go", ".rb": "ruby", ".rs": "rust",
    ".cs": "csharp", ".php": "php", ".kt": "kotlin", ".swift": "swift",
}


def language_from_file(path: str) -> str:
    """Broad language of a single file (used for per-test metadata/commands)."""
    return _EXT_LANGUAGE.get(Path(path).suffix.lower(), UNKNOWN)


@dataclass
class LanguageInfo:
    language: str = UNKNOWN
    confidence: str = "low"  # high | medium | low
    evidence: List[str] = field(default_factory=list)

    @property
    def instrumentation_language(self) -> Optional[str]:
        return _INSTRUMENTATION.get(self.language)

    def to_dict(self) -> Dict[str, object]:
        return {
            "language": self.language,
            "confidence": self.confidence,
            "instrumentation_language": self.instrumentation_language,
            "evidence": list(self.evidence),
        }


def detect_language_from_repo(path: str) -> LanguageInfo:
    """Infer the language/testbed from a local repository checkout."""
    root = Path(path).expanduser()
    if not root.exists() or not root.is_dir():
        return LanguageInfo(UNKNOWN, "low", [f"path not found: {path}"])

    has_node = (root / "package.json").exists() or any(True for _ in _iter_package_json(root))
    if has_node:
        playwright = _find_playwright(root)
        if playwright:
            return LanguageInfo(PLAYWRIGHT, "high", [playwright])
        if (root / "tsconfig.json").exists() or _has_ext(root, {".ts", ".tsx"}):
            return LanguageInfo(TYPESCRIPT, "high", ["TypeScript sources + package.json"])
        return LanguageInfo(JAVASCRIPT, "medium", ["package.json (no TypeScript/Playwright)"])

    if _is_python_project(root):
        return LanguageInfo(PYTHON, "high", ["python project files"])

    counts = _count_extensions(root)
    return _from_extension_counts(counts, source="repository scan")


def detect_js_test_runner(repo_path: str) -> Optional[str]:
    """Best JS/TS test runner for a checkout: playwright | vitest | jest | None."""
    root = Path(repo_path).expanduser()
    if not root.is_dir():
        return None
    all_deps: set = set()
    for pkg in _iter_package_json(root):
        all_deps |= _package_deps(pkg)
    for runner, deps in _JS_RUNNERS:
        if any(dep in all_deps for dep in deps):
            return runner
    return None


def detect_language_from_files(paths: Iterable[str]) -> LanguageInfo:
    """Infer the language from a set of changed file paths."""
    counts: Dict[str, int] = {}
    spec_ts = 0
    for p in paths:
        name = Path(p).name.lower()
        # `.spec.ts` / `.test.ts` are double extensions; Path.suffix only sees `.ts`.
        if name.endswith((".spec.ts", ".test.ts", ".spec.tsx", ".test.tsx")):
            spec_ts += 1
        ext = Path(p).suffix.lower()
        counts[ext] = counts.get(ext, 0) + 1
    return _from_extension_counts(counts, source="changed files", spec_ts=spec_ts)


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

def _from_extension_counts(counts: Dict[str, int], *, source: str, spec_ts: int = 0) -> LanguageInfo:
    total = sum(counts.values())
    if total == 0:
        return LanguageInfo(UNKNOWN, "low", [f"no files in {source}"])

    py = sum(v for k, v in counts.items() if k == ".py")
    ts = sum(v for k, v in counts.items() if k in (".ts", ".tsx"))
    js = sum(v for k, v in counts.items() if k in (".js", ".jsx", ".mjs", ".cjs"))

    if spec_ts and ts >= py:
        return LanguageInfo(
            PLAYWRIGHT, "high", [f"{spec_ts}/{total} changed files are Playwright specs"]
        )
    if py >= ts and py >= js and py:
        confidence = "high" if py / total >= 0.6 else "medium"
        return LanguageInfo(PYTHON, confidence, [f"{py}/{total} changed files are Python"])
    if ts and ts >= js:
        return LanguageInfo(TYPESCRIPT, "high", [f"{ts}/{total} changed files are TypeScript"])
    if js:
        return LanguageInfo(JAVASCRIPT, "medium", [f"{js}/{total} changed files are JavaScript"])
    return LanguageInfo(UNKNOWN, "low", [f"unrecognized extensions: {sorted(counts)}"])


def _iter_package_json(root: Path):
    for pkg in root.rglob("package.json"):
        if any(part in _SKIP_DIRS for part in pkg.relative_to(root).parts[:-1]):
            continue
        yield pkg


def _find_playwright(root: Path) -> Optional[str]:
    """Strongest signal first: playwright.config then any workspace dep."""
    for name in ("playwright.config.ts", "playwright.config.js", "playwright.config.mjs",
                 "playwright.config.cjs", "playwright.config.mts"):
        if (root / name).exists():
            return f"{name} present"
    for pkg in _iter_package_json(root):
        if any(dep in _package_deps(pkg) for dep in _PLAYWRIGHT_DEPS):
            rel = pkg.parent.relative_to(root)
            where = "package.json" if str(rel) == "." else f"{rel}/package.json"
            return f"{where}: @playwright/test"
    return None


def _package_deps(pkg: Path) -> set:
    try:
        data = json.loads(pkg.read_text())
    except (OSError, json.JSONDecodeError):
        return set()
    deps: Dict[str, str] = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        section = data.get(key)
        if isinstance(section, dict):
            deps.update(section)
    return set(deps.keys())


def _is_python_project(root: Path) -> bool:
    markers = ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
               "pytest.ini", "tox.ini")
    if any((root / m).exists() for m in markers):
        return True
    return _has_ext(root, {".py"})


def _has_ext(root: Path, exts: set) -> bool:
    return any(True for _ in _walk_exts(root, exts))


def _count_extensions(root: Path, max_files: int = 5000) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    seen = 0
    for sub in root.rglob("*"):
        if seen >= max_files:
            break
        if not sub.is_file():
            continue
        if any(part in _SKIP_DIRS for part in sub.relative_to(root).parts[:-1]):
            continue
        ext = sub.suffix.lower()
        if not ext:
            continue
        counts[ext] = counts.get(ext, 0) + 1
        seen += 1
    return counts


def _walk_exts(root: Path, exts: set):
    for sub in root.rglob("*"):
        if not sub.is_file():
            continue
        if any(part in _SKIP_DIRS for part in sub.relative_to(root).parts[:-1]):
            continue
        if sub.suffix.lower() in exts:
            yield sub
