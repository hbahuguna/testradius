"""Failure categorization and analysis."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List


def categorize_failure(message: str) -> str:
    m = message.lower()
    if "timeout" in m or "timed out" in m:
        return "timeout"
    if "navigation" in m or "goto" in m or "net::" in m:
        return "navigation"
    if "selector" in m or "locator" in m or "query" in m or "not found" in m or "element" in m:
        return "selector"
    if "network" in m or "xhr" in m or "fetch" in m:
        return "network"
    if "assert" in m or "expect" in m:
        return "assertion"
    return "unknown"


@dataclass
class FailureRecord:
    test_case_id: str
    message: str
    category: str = ""
    screenshot: str | None = None


@dataclass
class FailureAnalysis:
    failures: List[FailureRecord] = field(default_factory=list)
    categories: Counter = field(default_factory=Counter)

    def add(self, record: FailureRecord):
        if not record.category:
            record.category = categorize_failure(record.message)
        self.failures.append(record)
        self.categories[record.category] += 1
        return self

    def summary(self) -> Dict[str, Any]:
        return {
            "total_failures": len(self.failures),
            "by_category": dict(self.categories),
            "top_category": self.categories.most_common(1)[0][0] if self.categories else None,
        }
