"""Parsed result types returned by the TestRadius tool adapters (E3/T1).

The backend speaks JSON (and SSE for instrumentation). These dataclasses are
the single, typed shape the conversational flow and the CLI consume, so the raw
wire format never leaks past the tools layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TestRef:
    test_name: str
    test_file: str

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "TestRef":
        return cls(
            test_name=str(raw.get("test_name", "")),
            test_file=str(raw.get("test_file", "")),
        )


@dataclass
class SymbolSelection:
    """A changed symbol plus the tests TestRadius already maps to it."""

    symbol_name: str
    symbol_file: str
    symbol_summary: str = ""
    symbol_type: str = ""
    priority_risk_index: float = 0.0
    existing_tests: List[TestRef] = field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "SymbolSelection":
        return cls(
            symbol_name=str(raw.get("symbol_name", "")),
            symbol_file=str(raw.get("symbol_file", "")),
            symbol_summary=str(raw.get("symbol_summary", "") or ""),
            symbol_type=str(raw.get("symbol_type", "") or ""),
            priority_risk_index=float(raw.get("priority_risk_index", 0.0) or 0.0),
            existing_tests=[TestRef.from_raw(t) for t in raw.get("existing_tests", [])],
        )


@dataclass
class AnalyzeResult:
    """Parsed ``POST /projects/{id}/analyze-pr`` response."""

    project_id: int
    full_name: str
    pr_number: int
    commit_sha: str
    pr_files_analyzed: int
    symbols_selected: int
    tests_selected: int
    total_tests_reused: int
    pr_files: List[str] = field(default_factory=list)
    results: List[SymbolSelection] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return self.total_tests_reused == 0

    def to_raw(self) -> Dict[str, Any]:
        """Round-trip back to the backend/pipeline dict shape."""
        return {
            "project_id": self.project_id,
            "full_name": self.full_name,
            "pr_number": self.pr_number,
            "commit_sha": self.commit_sha,
            "pr_files_analyzed": self.pr_files_analyzed,
            "pr_files": list(self.pr_files),
            "symbols_selected": self.symbols_selected,
            "tests_selected": self.tests_selected,
            "total_tests_reused": self.total_tests_reused,
            "results": [
                {
                    "symbol_name": s.symbol_name,
                    "symbol_file": s.symbol_file,
                    "symbol_summary": s.symbol_summary,
                    "symbol_type": s.symbol_type,
                    "priority_risk_index": s.priority_risk_index,
                    "existing_tests": [
                        {"test_name": t.test_name, "test_file": t.test_file}
                        for t in s.existing_tests
                    ],
                }
                for s in self.results
            ],
        }

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "AnalyzeResult":
        return cls(
            project_id=int(raw.get("project_id", 0)),
            full_name=str(raw.get("full_name", "")),
            pr_number=int(raw.get("pr_number", 0)),
            commit_sha=str(raw.get("commit_sha", "")),
            pr_files_analyzed=int(raw.get("pr_files_analyzed", 0)),
            symbols_selected=int(raw.get("symbols_selected", 0)),
            tests_selected=int(raw.get("tests_selected", 0)),
            total_tests_reused=int(raw.get("total_tests_reused", 0)),
            pr_files=list(raw.get("pr_files") or raw.get("file_paths") or []),
            results=[SymbolSelection.from_raw(s) for s in raw.get("results", [])],
        )


@dataclass
class MappingEntry:
    """One product-symbol -> test-symbol mapping (EVIDENCE / APPROVED_TEST)."""

    product_symbol: str
    product_file: str
    test_symbol: str
    test_file: str
    confidence: float = 0.0
    reasoning: str = ""
    status: str = ""

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "MappingEntry":
        return cls(
            product_symbol=str(raw.get("product_symbol", "")),
            product_file=str(raw.get("product_file", "")),
            test_symbol=str(raw.get("test_symbol", "")),
            test_file=str(raw.get("test_file", "")),
            confidence=float(raw.get("confidence", 0.0) or 0.0),
            reasoning=str(raw.get("reasoning", "") or ""),
            status=str(raw.get("status", "") or ""),
        )


@dataclass
class EvidenceStatus:
    """Freshness of TestRadius evidence for a project.

    There is no dedicated evidence endpoint, so this is derived from the
    existing ``/projects/{id}/test-mapping`` data: evidence is "known" when the
    endpoint is reachable and "fresh" when it already maps tests for the changed
    files (or any files, when no paths are supplied).
    """

    known: bool
    fresh: bool
    mapping_count: int = 0
    covered_files: List[str] = field(default_factory=list)
    reason: str = ""

    @property
    def needs_instrumentation(self) -> bool:
        # If we cannot tell, do NOT auto-run — the flow asks (D10).
        return (not self.known) or (not self.fresh)


@dataclass
class InstrumentationResult:
    """Parsed SSE stream from ``POST /projects/{id}/instrumentation/run``."""

    status: str = "UNKNOWN"  # COMPLETED | CANCELLED | ERROR | UNKNOWN
    edges: int = 0
    error: Optional[str] = None
    events: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "COMPLETED" and not self.error
