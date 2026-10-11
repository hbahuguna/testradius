"""Tool adapters used by the conversational flow.

Thin wrapper over the real E3/T1 adapters in ``tia_agent.tools``: the flow only
depends on the small ``Toolbox`` protocol, and this class bridges it to
``TestRadiusTools`` with graceful degradation (an unavailable backend means
"evidence unknown, ask before instrumenting" — never auto-run, D10).
"""

from __future__ import annotations

from typing import List, Optional, Protocol

from ..radius_client import ProjectInfo, RadiusClient
from ..tools import TestRadiusTools
from ..tools.models import EvidenceStatus, InstrumentationResult

# Backwards-compatible name: the flow and its tests refer to ``Evidence``.
Evidence = EvidenceStatus


class Toolbox(Protocol):
    def check_evidence(self, repo: str, project: ProjectInfo,
                       file_paths: Optional[List[str]] = None) -> EvidenceStatus: ...

    def run_instrumentation(self, repo: str, project: ProjectInfo,
                            file_paths: Optional[List[str]] = None) -> InstrumentationResult: ...


class RadiusToolbox:
    """Toolbox backed by the TestRadius backend via ``TestRadiusTools``."""

    def __init__(
        self,
        radius: RadiusClient,
        *,
        tools: Optional[TestRadiusTools] = None,
        language: Optional[str] = None,
        local_path: Optional[str] = None,
        repo_url: Optional[str] = None,
    ):
        self.radius = radius
        self.tools = tools if tools is not None else TestRadiusTools(radius)
        self.language = language
        self.local_path = local_path
        self.repo_url = repo_url

    def check_evidence(self, repo: str, project: ProjectInfo,
                       file_paths: Optional[List[str]] = None) -> EvidenceStatus:
        try:
            return self.tools.check_evidence(project, file_paths)
        except Exception as e:  # noqa: BLE001 - unknown => ask, never auto-run
            return EvidenceStatus(
                known=False, fresh=False, reason=f"evidence check failed: {e}"
            )

    def run_instrumentation(self, repo: str, project: ProjectInfo,
                            file_paths: Optional[List[str]] = None) -> InstrumentationResult:
        try:
            return self.tools.run_instrumentation(
                project,
                language=self.language,
                local_path=self.local_path,
                repo_url=self.repo_url,
            )
        except Exception as e:  # noqa: BLE001 - surface as a failed result, never crash the flow
            return InstrumentationResult(status="ERROR", error=str(e))
