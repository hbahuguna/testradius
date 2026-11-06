"""GitHub issue connector (STORY-E2B-005.3).

Defaults to dry-run for safety. Real filing can use `gh` CLI when explicitly enabled.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from .base import BaseIssueConnector
from ..bugs.generator import BugReport, _norm_text


class GitHubConnector(BaseIssueConnector):
    name = "github"

    def __init__(
        self,
        repo: Optional[str] = None,
        *,
        dry_run: bool = True,
        existing_issues: Optional[List[Dict[str, Any]]] = None,
        gh_path: str = "gh",
        labels: Optional[List[str]] = None,
    ):
        self.repo = repo  # owner/repo
        self.dry_run = dry_run
        self._existing = existing_issues or []
        self.gh_path = gh_path
        self.default_labels = labels or []

    def list_existing(self, **kwargs: Any) -> List[Dict[str, Any]]:
        if self._existing:
            return list(self._existing)
        # Best-effort: query via gh if repo configured and not dry-run/list explicitly desired.
        if not self.repo or not shutil.which(self.gh_path):
            return []
        try:
            cmd = [self.gh_path, "issue", "list", "--repo", self.repo, "--state", "all", "--limit", "100", "--json", "number,title,url,state"]
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode != 0:
                return []
            data = json.loads(res.stdout or "[]")
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def file(self, report: BugReport, **kwargs: Any) -> Dict[str, Any]:
        existing = kwargs.get("existing_issues")
        if self.is_duplicate(report, existing=existing):
            return {"status": "duplicate", "connector": self.name, "title": report.title, "fingerprint": report.fingerprint}

        body = report.render_markdown()
        labels = list(dict.fromkeys((self.default_labels or []) + (report.labels or [])))
        payload = {
            "connector": self.name,
            "repo": self.repo,
            "title": report.title,
            "body": body,
            "labels": labels,
            "fingerprint": report.fingerprint,
            "evidence": report.evidence.to_dict(),
        }

        if self.dry_run:
            return {
                "status": "dry_run",
                "url": (f"https://github.com/{self.repo}/issues/(dry-run)" if self.repo else "dry-run://local/issue"),
                **payload,
            }

        if not self.repo:
            return {"status": "error", "error": "GitHub repo not configured", **payload}
        if not shutil.which(self.gh_path):
            return {"status": "error", "error": f"`{self.gh_path}` CLI not found; install GitHub CLI or use dry_run=True", **payload}

        cmd = [self.gh_path, "issue", "create", "--repo", self.repo, "--title", report.title, "--body", body]
        for label in labels[:10]:
            cmd += ["--label", label]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode != 0:
                return {"status": "error", "error": (res.stderr or res.stdout or "gh issue create failed").strip(), **payload}
            url = _norm_text(res.stdout)
            return {"status": "filed", "url": url, **payload}
        except Exception as e:
            return {"status": "error", "error": str(e), **payload}
