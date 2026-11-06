"""Structured models for Vision QA findings (STORY-E2B-004.2)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


QA_CATEGORIES = ("layout", "contrast", "clipping", "overlap", "responsive")
SEVERITIES = ("info", "low", "medium", "high", "critical")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class VisionFinding:
    category: str  # layout|contrast|clipping|overlap|responsive|...
    issue: str  # short issue summary; "none"/"ok" for clean checks
    severity: str = "info"
    confidence: float = 0.0
    description: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    suggestion: str = ""
    location: Optional[str] = None  # e.g. "header", "hero image", "footer CTA"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Backward-compatible alias expected by older consumers
        d["type"] = self.category
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisionFinding":
        category = data.get("category") or data.get("type") or "unknown"
        return cls(
            category=str(category),
            issue=str(data.get("issue", "")),
            severity=str(data.get("severity", "info")),
            confidence=float(data.get("confidence", 0.0) or 0.0),
            description=str(data.get("description", "")),
            evidence=dict(data.get("evidence") or {}),
            suggestion=str(data.get("suggestion", "")),
            location=data.get("location"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class VisionAnalysisResult:
    screenshot_path: str
    model: str
    provider: str
    findings: List[VisionFinding] = field(default_factory=list)
    summary: str = ""
    raw_response: Optional[str] = None
    analyzed_at: str = field(default_factory=_utc_now)
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        if self.error:
            return False
        for f in self.findings:
            sev = (f.severity or "").lower()
            issue = (f.issue or "").lower()
            if sev in {"medium", "high", "critical"} and issue not in {"none", "ok", "pass", "no issue"}:
                return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "screenshot_path": self.screenshot_path,
            "model": self.model,
            "provider": self.provider,
            "findings": [f.to_dict() for f in self.findings],
            "summary": self.summary,
            "analyzed_at": self.analyzed_at,
            "passed": self.passed,
            "error": self.error,
            "metadata": self.metadata,
        }

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(__import__("json").dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path
