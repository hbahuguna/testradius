"""Mock vision provider for tests and demos."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .base import BaseVisionProvider
from ..models import QA_CATEGORIES


class MockVisionProvider(BaseVisionProvider):
    name = "mock"

    def __init__(self, mode: str = "clean", findings: Optional[list[dict[str, Any]]] = None):
        self.mode = mode
        self.findings = findings

    def analyze_image(
        self,
        image_path: str,
        prompt: str,
        *,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[Dict[str, Any], Optional[str], Optional[str]]:
        name = Path(image_path).name.lower()
        if self.findings is not None:
            payload = {"summary": "Mock analysis with injected findings.", "findings": self.findings}
            return payload, __import__("json").dumps(payload), None

        mode = self.mode
        if "issue" in name or "broken" in name:
            mode = "issues"
        if "contrast" in name:
            mode = "contrast"

        if mode == "contrast":
            findings = [
                {"category": "contrast", "issue": "Low contrast text", "severity": "medium", "confidence": 0.88,
                 "description": "Body text appears low contrast against background.", "location": "main content",
                 "suggestion": "Increase text contrast to meet WCAG AA."},
            ]
            for c in QA_CATEGORIES:
                if c != "contrast":
                    findings.append({"category": c, "issue": "none", "severity": "info", "confidence": 0.9, "description": "No issue detected.", "location": "", "suggestion": ""})
            payload = {"summary": "Contrast issue detected.", "findings": findings}
            return payload, __import__("json").dumps(payload), None

        if mode == "issues":
            findings = [
                {"category": "layout", "issue": "Misaligned CTA", "severity": "medium", "confidence": 0.82,
                 "description": "Primary CTA appears misaligned with content grid.", "location": "hero", "suggestion": "Align CTA to grid."},
                {"category": "overlap", "issue": "Text overlaps image", "severity": "high", "confidence": 0.91,
                 "description": "Heading text overlaps hero image.", "location": "hero", "suggestion": "Adjust spacing/z-index."},
            ]
            for c in QA_CATEGORIES:
                if c not in {"layout", "overlap"}:
                    findings.append({"category": c, "issue": "none", "severity": "info", "confidence": 0.9, "description": "No issue detected.", "location": "", "suggestion": ""})
            payload = {"summary": "Layout and overlap issues detected.", "findings": findings}
            return payload, __import__("json").dumps(payload), None

        findings = [
            {"category": c, "issue": "none" if c != "contrast" else "ok", "severity": "info", "confidence": 0.9,
             "description": "No visual issue detected.", "location": "", "suggestion": ""}
            for c in QA_CATEGORIES
        ]
        payload = {"summary": "No significant visual QA issues detected.", "findings": findings}
        return payload, __import__("json").dumps(payload), None
