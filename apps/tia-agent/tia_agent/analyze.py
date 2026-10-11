"""The `analyze` pipeline: license gate -> resolve project -> analyze-pr -> result.

This is the single entry the CLI's `analyze` subcommand and the REPL both call,
so license validation + run metering always fire on the same path.
"""

from __future__ import annotations

import hashlib
import platform
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from . import __version__
from .config import TiaConfig
from .license_guard import LicenseGuard
from .output import SCHEMA_VERSION, build_run_commands
from .radius_client import ProjectInfo, RadiusClient
from .tools import TestRadiusTools
from .tools.fs import count_test_cases, discover_tests_fallback, validate_tests
from .tools.github import GitHubClient, filter_source_files
from .tools.language import detect_js_test_runner, language_from_file

#: Fraction of the suite above which we recommend a full run (E5/O1).
SAFETY_RATIO = 0.30


@dataclass
class TiaResult:
    tia_run_id: str
    repo: str
    pr_number: int
    files_analyzed: int
    symbols_selected: int
    tests_selected: int
    total_affected_tests: int
    total_tests_in_repo: Optional[int]
    fallback_used: bool
    fallback_reason: Optional[str]
    confidence: str
    tests: List[Dict[str, Any]] = field(default_factory=list)
    run_commands: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    changed_files: List[str] = field(default_factory=list)
    safety_flag: bool = False
    impacted_ratio: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "repo": self.repo,
            "pr_number": self.pr_number,
            "files_analyzed": self.files_analyzed,
            "changed_files": list(self.changed_files),
            "symbols_selected": self.symbols_selected,
            "tests_selected": self.tests_selected,
            "total_affected_tests": self.total_affected_tests,
            "total_tests_in_repo": self.total_tests_in_repo,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "confidence": self.confidence,
            "safety_flag": self.safety_flag,
            "impacted_ratio": self.impacted_ratio,
            "tests": self.tests,
            "run_commands": self.run_commands,
            "tia_run_id": self.tia_run_id,
            "notes": self.notes,
        }


class AnalyzeRunner:
    def __init__(
        self,
        config: TiaConfig,
        license_guard: LicenseGuard,
        radius: RadiusClient,
        github: Optional[GitHubClient] = None,
    ):
        self.config = config
        self.license_guard = license_guard
        self.radius = radius
        self.tools = TestRadiusTools(radius)
        self.github = github if github is not None else GitHubClient(config.github_token)

    @classmethod
    def build(cls, config: TiaConfig, license_service_url: Optional[str] = None) -> "AnalyzeRunner":
        guard = LicenseGuard(config)
        radius = RadiusClient(config.radius_url, config.radius_token)
        return cls(config, guard, radius)

    def set_github_token(self, token: str) -> None:
        """Swap in a token after the user provides one (private repos)."""
        self.github = GitHubClient(token)

    def fetch_files(
        self,
        repo: str,
        pr_number: int,
        file_paths: Optional[List[str]] = None,
    ) -> List[str]:
        """Resolve the PR's changed source files.

        Explicit ``file_paths`` win (no network). Otherwise fetch the PR file
        list from GitHub and filter it down to source files.
        """
        if file_paths:
            return list(file_paths)
        files = self.github.get_pr_files(repo, int(pr_number))
        return filter_source_files(files)

    # ------------------------------------------------------------------
    # Composable steps. The conversational flow (A3) calls these directly so
    # it can explain each step and gate instrumentation in between; `run()`
    # composes them for the non-interactive CLI path.
    # ------------------------------------------------------------------
    def ensure_license(self) -> None:
        self.license_guard.ensure_valid()

    def resolve(self, repo: str) -> "ProjectInfo":
        return self.tools.resolve_project(repo)

    def analyze(
        self,
        project: "ProjectInfo",
        repo: str,
        pr_number: int,
        commit_sha: str = "main",
        file_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Evidence-first: call analyze-pr and use its mappings verbatim."""
        result = self.tools.analyze_pr(
            project,
            full_name=repo,
            pr_number=pr_number,
            commit_sha=commit_sha,
            file_paths=file_paths,
        )
        return result.to_raw()

    def meter(self, result: TiaResult, repo: str, duration: float) -> None:
        """Meter a run — summary metadata only (D12). Call ONLY on success."""
        self.license_guard.record_run(
            run_id=result.tia_run_id,
            repo_hash=self.repo_hash(repo),
            metadata={
                "file_count": result.files_analyzed,
                "test_count": result.total_affected_tests,
                "language": result.tests[0]["language"] if result.tests else "unknown",
                "duration_seconds": round(duration, 3),
                "os": platform.system().lower(),
                "agent_version": __version__,
            },
        )

    def run(
        self,
        repo: str,
        pr_number: int,
        commit_sha: str = "main",
        file_paths: Optional[List[str]] = None,
        on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        repo_path: Optional[str] = None,
    ) -> TiaResult:
        emit = on_event or (lambda *_: None)

        # 1. license gate
        self.ensure_license()
        emit("license_ok", {})

        # 2. resolve project
        project = self.resolve(repo)
        emit("project_resolved", {"project_id": project.id, "project_name": project.name})

        # 3. analyze (evidence-first) + fallback + validation
        started = time.time()
        repo_path = repo_path or getattr(self.config, "repo_path", "") or None
        raw = self.analyze(project, repo, pr_number, commit_sha, file_paths)
        result = self.to_result(raw, repo, pr_number, repo_path=repo_path,
                                changed_files=file_paths)
        emit("analyzed", {"result": result})

        # 4. meter only after a successful analysis (D1/D12)
        self.meter(result, repo, time.time() - started)
        emit("metered", {"total_affected_tests": result.total_affected_tests})
        return result

    def to_result(
        self,
        raw: Dict[str, Any],
        repo: str,
        pr_number: int,
        *,
        repo_path: Optional[str] = None,
        language: Optional[str] = None,
        changed_files: Optional[List[str]] = None,
    ) -> TiaResult:
        """Turn the raw analyze-pr response into a validated ``TiaResult``.

        Pipeline (E4/F1): evidence-first -> dedupe -> fallback discovery ->
        existence check. Nothing here invents tests: fallback tests come from a
        read-only filesystem scan of the user's checkout.
        """
        symbols = int(raw.get("symbols_selected", 0))
        tests_selected = int(raw.get("tests_selected", 0))
        evidence_total = int(raw.get("total_tests_reused", 0))
        pr_files = raw.get("pr_files") or raw.get("file_paths") or list(changed_files or [])
        notes = [f"analyzed via TestRadius backend at {self.radius.base_url}"]

        # 1. Evidence-first: dedupe the backend's mappings by (file, name).
        tests = _collect_tests(raw.get("results", []))

        # 2. Fallback decision: empty or sparse evidence.
        fallback_used = symbols == 0 or evidence_total == 0
        fallback_reason = None
        if fallback_used:
            fallback_reason = (
                "no impacted symbols found for the PR files; run the full test suite"
                if symbols == 0
                else "impacted symbols found but no reusable test mappings exist; "
                     "run the full test suite"
            )

        # 3. Existence check against the local checkout (when we have one).
        if repo_path and tests:
            check = validate_tests(tests, repo_path)
            if check.missing:
                notes.append(
                    f"dropped {len(check.missing)} test file(s) not found in repo: "
                    + ", ".join(sorted(set(check.missing))[:5])
                )
            tests = check.valid
            if not tests and not fallback_used:
                fallback_used = True
                fallback_reason = (
                    "reported tests were not found in the repo; run the full test suite"
                )

        # 4. Deterministic fallback: discover local tests (read-only).
        if repo_path and not tests and fallback_used:
            discovered = discover_tests_fallback(pr_files or changed_files, repo_path, language)
            if discovered:
                tests = discovered
                fallback_reason = (
                    f"{fallback_reason} — discovered {len(discovered)} local test file(s)"
                )
                notes.append(f"discovered {len(discovered)} local test file(s) as fallback")

        total_affected = len(tests) if repo_path else evidence_total
        # No usable evidence ⇒ low confidence, even if fallback found tests.
        confidence = "low" if fallback_used else _confidence(symbols, tests_selected, total_affected)

        # 5. Suite size + safety cap (E5/O1). Ratio only when we know the suite.
        total_tests_in_repo = _suite_size(raw, repo_path, language)
        impacted_ratio = None
        safety_flag = False
        if total_tests_in_repo:
            impacted_ratio = round(total_affected / total_tests_in_repo, 4)
            safety_flag = impacted_ratio > SAFETY_RATIO and not fallback_used

        runner = detect_js_test_runner(repo_path) if repo_path else None
        files_analyzed = int(raw.get("pr_files_analyzed") or len(pr_files or []))

        return TiaResult(
            tia_run_id=str(uuid.uuid4()),
            repo=repo,
            pr_number=pr_number,
            files_analyzed=files_analyzed,
            symbols_selected=symbols,
            tests_selected=int(tests_selected),
            total_affected_tests=int(total_affected),
            total_tests_in_repo=total_tests_in_repo,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            confidence=confidence,
            tests=tests,
            run_commands=build_run_commands(tests, runner=runner),
            notes=notes,
            changed_files=list(pr_files or []),
            safety_flag=safety_flag,
            impacted_ratio=impacted_ratio,
        )

    @staticmethod
    def repo_hash(repo: str) -> str:
        return hashlib.sha256(repo.encode()).hexdigest()


def _collect_tests(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten analyze-pr results, deduped by (test_file, test_name)."""
    tests: List[Dict[str, Any]] = []
    seen: set = set()
    for item in results:
        symbol_name = item.get("symbol_name", "?")
        for t in item.get("existing_tests", []):
            test_file = t.get("test_file", "")
            test_name = t.get("test_name", "")
            if (test_file, test_name) in seen:
                continue
            seen.add((test_file, test_name))
            tests.append(
                {
                    "file": test_file,
                    "name": test_name,
                    "nodeid": f"{test_file}::{test_name}",
                    "language": language_from_file(test_file),
                    "reason": symbol_name,
                }
            )
    return tests


def _confidence(symbols: int, tests_selected: int, total_affected: int) -> str:
    if symbols == 0 and total_affected == 0:
        return "low"
    if symbols > 0 and tests_selected > 0:
        return "high"
    if symbols > 0 or total_affected > 0:
        return "medium"
    return "low"


def _suite_size(
    raw: Dict[str, Any],
    repo_path: Optional[str],
    language: Optional[str],
) -> Optional[int]:
    """Local suite size for the safety ratio: count cases if we have a checkout,
    else use whatever the backend reported."""
    if repo_path:
        size = count_test_cases(repo_path, language)
        if size:
            return size
    backend_total = raw.get("total_tests_in_repo")
    try:
        return int(backend_total) if backend_total else None
    except (TypeError, ValueError):
        return None