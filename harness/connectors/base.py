"""Connector interface for filing bug reports (STORY-E2B-005.3)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from ..bugs.generator import BugReport, _norm_text


class BaseIssueConnector(ABC):
    name: str = "base"

    @abstractmethod
    def file(self, report: BugReport, **kwargs: Any) -> Dict[str, Any]:
        """File a report and return result dict with status/url/id/error."""
        raise NotImplementedError

    @abstractmethod
    def list_existing(self, **kwargs: Any) -> List[Dict[str, Any]]:
        """Return existing issues/tickets for dedup (best effort)."""
        raise NotImplementedError

    def is_duplicate(self, report: BugReport, existing: Optional[List[Dict[str, Any]]] = None) -> bool:
        existing = existing if existing is not None else self.list_existing()
        title = _norm_text(report.title).lower()
        fp = _norm_text(report.fingerprint).lower()
        for issue in existing or []:
            it = _norm_text(issue.get("title")).lower()
            ifp = _norm_text(issue.get("fingerprint")).lower()
            if it and title and (it == title or it in title or title in it):
                return True
            if fp and ifp and fp == ifp:
                return True
        return False
