"""TestRadius tool adapters (E3/T1).

``TestRadiusTools`` is the typed facade the agent uses for the four TestRadius
operations. Each method returns a parsed dataclass from ``tools.models`` (or a
``ProjectInfo``), so callers never touch the raw wire format.
"""

from __future__ import annotations

from typing import List, Optional

from ..radius_client import ProjectInfo, RadiusClient
from .models import (
    AnalyzeResult,
    EvidenceStatus,
    InstrumentationResult,
    MappingEntry,
)
from .project import resolve_project_for_repo

__all__ = [
    "TestRadiusTools",
    "resolve_project_for_repo",
    "ProjectInfo",
    "AnalyzeResult",
    "EvidenceStatus",
    "InstrumentationResult",
    "MappingEntry",
]


class TestRadiusTools:
    __test__ = False  # not a pytest test class (name collision)

    def __init__(self, radius: RadiusClient):
        self.radius = radius

    # -- resolve_project ----------------------------------------------------
    def resolve_project(self, repo: str) -> ProjectInfo:
        """Map ``owner/repo`` to a registered TestRadius project."""
        return resolve_project_for_repo(self.radius, repo)

    def register_project(self, repo: str, description: Optional[str] = None) -> ProjectInfo:
        """Create a project for ``repo`` if it is not already registered."""
        try:
            return self.resolve_project(repo)
        except Exception:  # noqa: BLE001 - not found => create it
            return self.radius.create_project(repo, description)

    # -- check_evidence -----------------------------------------------------
    def check_evidence(
        self,
        project: ProjectInfo,
        file_paths: Optional[List[str]] = None,
    ) -> EvidenceStatus:
        """Derive evidence freshness from existing test mappings."""
        return self.radius.check_evidence(project.id, file_paths)

    # -- run_instrumentation ------------------------------------------------
    def run_instrumentation(
        self,
        project: ProjectInfo,
        *,
        language: Optional[str] = None,
        testbed_name: Optional[str] = None,
        local_path: Optional[str] = None,
        repo_url: Optional[str] = None,
        run_fresh: bool = False,
        ensure_feature: bool = True,
    ) -> InstrumentationResult:
        """Run instrumentation, enabling the feature flag first if needed."""
        if ensure_feature:
            self.radius.ensure_feature(project.id, "instrumentation")
        return self.radius.run_instrumentation(
            project.id,
            repo_url=repo_url,
            run_fresh=run_fresh,
            language=language,
            testbed_name=testbed_name,
            local_path=local_path,
        )

    # -- analyze_pr ---------------------------------------------------------
    def analyze_pr(
        self,
        project: ProjectInfo,
        *,
        full_name: str,
        pr_number: int,
        commit_sha: str = "main",
        file_paths: Optional[List[str]] = None,
    ) -> AnalyzeResult:
        raw = self.radius.analyze_pr(
            project_id=project.id,
            full_name=full_name,
            pr_number=pr_number,
            commit_sha=commit_sha,
            file_paths=file_paths,
        )
        result = AnalyzeResult.from_raw(raw)
        if not result.pr_files and file_paths:
            result.pr_files = list(file_paths)
        return result
