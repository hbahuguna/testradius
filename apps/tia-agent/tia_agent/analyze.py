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
from .errors import LicenseError
from .license_guard import LicenseGuard
from .output import SCHEMA_VERSION, build_run_commands, canonical_nodeid
from .radius_client import ProjectInfo, RadiusClient
from .tools import TestRadiusTools
from .tools.fs import count_test_cases, discover_tests_fallback, validate_tests
from .tools.github import GitHubClient, filter_source_files
from .tools.language import detect_js_test_runner, language_from_file

#: Fraction of the suite above which we recommend a full run (E5/O1).
SAFETY_RATIO = 0.30

#: Per-test confidence ranking (V2): when the same test is selected for several
#: changed symbols, the strongest occurrence wins and carries its reason path.
_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


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
    evidence_built_at_sha: Optional[str] = None
    stale_evidence: bool = False
    stale_evidence_reason: Optional[str] = None
    evidence_unversioned: bool = False

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
            "evidence_built_at_sha": self.evidence_built_at_sha,
            "stale_evidence": self.stale_evidence,
            "stale_evidence_reason": self.stale_evidence_reason,
            "evidence_unversioned": self.evidence_unversioned,
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

    def meter(self, result: TiaResult, repo: str, duration: float) -> Optional[str]:
        """Meter a run — summary metadata only (D12). Call ONLY on success.

        Metering is soft: if the license lapses mid-session, the quota is hit at
        record time, or the server is unreachable, the already-completed analysis
        is still returned. The failure is surfaced as a warning string (and a
        note on the result) instead of discarding the work; a run that fails to
        meter is never counted (D1).
        """
        try:
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
        except LicenseError as e:
            warning = str(e)
            result.notes.append(warning)
            return warning
        return None

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

        # 4. meter only after a successful analysis (D1/D12). Soft failure:
        #    a completed analysis is still returned, just not counted.
        warning = self.meter(result, repo, time.time() - started)
        if warning:
            emit("meter_warning", {"message": warning})
        else:
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

        # 2b. Truncation safety (S1). The backend caps symbol selection; if the
        #     cap dropped symbols that already have test mappings, the partial
        #     result is incomplete, so we surface it and force a full-suite
        #     fallback rather than silently running a subset.
        if raw.get("truncated"):
            symbols_total = int(raw.get("symbols_total") or 0)
            max_symbols = raw.get("max_symbols")
            limit_txt = f" (limit {max_symbols})" if max_symbols is not None else ""
            if raw.get("truncation_dropped_tests"):
                notes.append(
                    f"symbol selection truncated: analyzed {symbols} of "
                    f"{symbols_total} changed symbols{limit_txt}; dropped symbols "
                    "have test mappings — forcing full-suite fallback"
                )
                fallback_used = True
                fallback_reason = (
                    "symbol selection was truncated and dropped symbols with test "
                    "mappings; run the full test suite"
                )
                # Discard the partial set so the deterministic discovery below
                # yields the complete local suite instead of an incomplete subset.
                if repo_path:
                    tests = []
            else:
                notes.append(
                    f"symbol selection truncated: analyzed {symbols} of "
                    f"{symbols_total} changed symbols{limit_txt}; no impacted tests "
                    "detected beyond the cap"
                )

        # 2c. Stale evidence safety (D2). Mappings are pinned to the testbed
        #     commit they were built against; when analyzing a drifted commit,
        #     the evidence may not reflect the current code — force a full-suite
        #     fallback instead of silently selecting on stale data.
        evidence_built_at_sha = raw.get("evidence_built_at_sha")
        if raw.get("stale_evidence"):
            notes.append(
                raw.get("stale_evidence_reason")
                or "evidence is stale (built against a different commit)"
            )
            fallback_used = True
            fallback_reason = (
                "impacted symbols exist but evidence was built against a different "
                "commit; run the full test suite"
            )
            if repo_path:
                tests = []
        elif raw.get("evidence_unversioned"):
            notes.append(
                "evidence has no recorded build commit (mapped before SHA "
                "stamping); freshness could not be verified"
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

        # Canonical numerator (S3): distinct selected test nodeids — the same
        # unit as the suite denominator. (Previously this used the raw mapping
        # count when no checkout was present, a different unit.)
        total_affected = len(tests)
        # No usable evidence ⇒ low confidence, even if fallback found tests.
        base_confidence = _confidence(symbols, tests_selected, total_affected)
        has_runtime = any(t.get("confidence") == "high" for t in tests)
        static_only = sum(1 for t in tests if t.get("confidence") == "medium")
        if static_only:
            notes.append(
                f"{static_only} test(s) selected by static reachability "
                "(import/call graph) without runtime evidence — confidence=medium"
            )
        if fallback_used:
            confidence = "low"
        elif static_only and not has_runtime:
            # Everything we selected is statically reached but never executed.
            confidence = "medium"
        else:
            confidence = base_confidence

        # 5. Suite size + safety cap (E5/O1/S3). Numerator and denominator share
        #    one unit (collected nodeids) so impacted_ratio / reduction are
        #    internally consistent.
        total_tests_in_repo = _suite_size(raw, repo_path, language)
        if fallback_used and total_tests_in_repo:
            # Falling back to the full suite: no reduction is claimed.
            total_affected = total_tests_in_repo
        impacted_ratio = (
            round(total_affected / total_tests_in_repo, 4)
            if total_tests_in_repo
            else None
        )
        safety_flag = bool(
            impacted_ratio is not None
            and impacted_ratio > SAFETY_RATIO
            and not fallback_used
        )

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
            evidence_built_at_sha=evidence_built_at_sha,
            stale_evidence=bool(raw.get("stale_evidence")),
            stale_evidence_reason=raw.get("stale_evidence_reason"),
            evidence_unversioned=bool(raw.get("evidence_unversioned")),
        )

    @staticmethod
    def repo_hash(repo: str) -> str:
        return hashlib.sha256(repo.encode()).hexdigest()


def _collect_tests(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten analyze-pr results, deduped by (test_file, test_name).

    Preserves the per-test ``confidence``/``reason`` produced by runtime +
    static fusion (S2): a test that only statically reaches a changed symbol is
    kept with ``confidence='medium'`` rather than dropped.

    V2: the ``reason`` is a ``changed symbol -> test`` path. The backend
    already emits one; if it ever omits it (older backend), we synthesize a
    path from the symbol entry so a selection is never opaque. When the same
    test is selected for several symbols, the strongest confidence wins and
    carries the reason path of that occurrence.
    """
    tests: List[Dict[str, Any]] = []
    seen: set = set()
    for item in results:
        symbol_name = item.get("symbol_name") or "?"
        symbol_file = item.get("symbol_file") or "?"
        for t in item.get("existing_tests", []):
            test_file = t.get("test_file", "")
            test_name = t.get("test_name", "")
            nodeid = canonical_nodeid(test_file, test_name)
            confidence = t.get("confidence") or "high"
            reason = t.get("reason") or (
                f"changed_symbol:{symbol_name}@{symbol_file} -> selected -> {nodeid}"
            )
            # O1: dedupe against the canonical nodeid so two representations of
            # the same test (method-only vs already-qualified) collapse into one.
            if nodeid in seen:
                # Same test selected for another symbol: keep the strongest
                # confidence (high beats medium) and its reason path.
                for existing in tests:
                    if existing["nodeid"] == nodeid:
                        if (
                            _CONFIDENCE_RANK.get(confidence, 0)
                            > _CONFIDENCE_RANK.get(existing.get("confidence"), 0)
                        ):
                            existing["confidence"] = confidence
                            existing["reason"] = reason
                        break
                continue
            seen.add(nodeid)
            tests.append(
                {
                    "file": test_file,
                    "name": test_name,
                    "nodeid": nodeid,
                    "language": language_from_file(test_file),
                    "reason": reason,
                    "confidence": confidence,
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
    """Canonical suite size (S3): the number of distinct collected test nodeids.

    The backend is authoritative (it counts ``TestSymbol`` nodeids for the
    project). We only fall back to a local ``def test_*`` count when the backend
    did not report one (older backend), since that count is an approximation of
    the same unit.
    """
    backend_total = raw.get("total_tests_in_repo")
    try:
        if backend_total:
            return int(backend_total)
    except (TypeError, ValueError):
        pass
    if repo_path:
        size = count_test_cases(repo_path, language)
        if size:
            return size
    return None