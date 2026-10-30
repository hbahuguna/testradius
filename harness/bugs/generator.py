import json
from pathlib import Path


class BugFiler:
    def __init__(self, existing: list = None):
        self.existing = existing or []

    def dedup(self, title: str) -> bool:
        return any(b.get("title") == title for b in self.existing)

    def generate(self, findings: list, evidence: str):
        ticket = {
            "title": findings[0]["type"] + " issue" if findings else "Visual issue",
            "steps": ["Navigate to page", "Observe issue"],
            "evidence": evidence,
            "severity": "medium",
            "suspected_cause": "CSS/layout",
        }
        return ticket

    def file(self, findings: list, evidence: str, approved: bool = False):
        if not approved:
            raise PermissionError("Approval required before filing")
        t = self.generate(findings, evidence)
        if self.dedup(t["title"]):
            return {"status": "duplicate", "ticket": t}
        return {"status": "filed", "ticket": t, "url": "https://github.com/org/repo/issues/123"}
