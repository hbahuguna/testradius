"""GitHub PR intake (E3/T3): find the source files a PR touches.

Talks to the GitHub REST API directly with httpx (same transport-injection
pattern as ``RadiusClient``) so private repos work with a user-supplied token.
No PyGithub dependency. The changed-source-file set is what downstream TIA
uses to reason about the PR.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from ..errors import GitHubAuthError, GitHubError

GITHUB_API = "https://api.github.com"
_PER_PAGE = 100

# Path segments that rarely carry the symbols TIA reasons about.
_EXCLUDE_DIRS = {
    ".git", ".github", "node_modules", "vendor", "dist", "build", "out",
    ".next", ".nuxt", ".svelte-kit", "venv", ".venv", "__pycache__",
    "docs", "doc", "site", "coverage", "htmlcov", "target",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
}

# Non-source suffixes (docs, assets, lockfiles, config) excluded from impact analysis.
_EXCLUDE_SUFFIXES = (
    ".md", ".markdown", ".rst", ".txt", ".adoc",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp", ".pdf",
    ".lock", ".sum", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".min.js", ".min.css", ".map", ".snap",
)

# PR statuses that meaningfully change source symbols (deletions are skipped).
_CHANGE_STATUSES = {"added", "modified", "renamed", "copied", "changed"}


@dataclass
class PrFile:
    filename: str
    status: str = "modified"
    additions: int = 0
    deletions: int = 0
    previous_filename: Optional[str] = None

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "PrFile":
        return cls(
            filename=raw.get("filename", ""),
            status=raw.get("status", "modified"),
            additions=int(raw.get("additions", 0) or 0),
            deletions=int(raw.get("deletions", 0) or 0),
            previous_filename=raw.get("previous_filename"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filename": self.filename,
            "status": self.status,
            "additions": self.additions,
            "deletions": self.deletions,
            "previous_filename": self.previous_filename,
        }


def is_source_file(path: str) -> bool:
    """True when a changed path is likely to carry testable symbols."""
    p = (path or "").replace("\\", "/").strip().strip("/")
    if not p:
        return False
    parts = [seg for seg in p.split("/") if seg]
    if any(seg in _EXCLUDE_DIRS for seg in parts[:-1]):
        return False
    name = parts[-1]
    if name.startswith("."):
        return False
    low = name.lower()
    if any(low.endswith(suffix) for suffix in _EXCLUDE_SUFFIXES):
        return False
    return True


def filter_source_files(files: List[PrFile]) -> List[str]:
    """Changed source paths (deduped, ordered). Excludes docs/vendor/assets."""
    out: List[str] = []
    seen: set = set()
    for f in files:
        if f.status and f.status.lower() not in _CHANGE_STATUSES:
            continue
        if not is_source_file(f.filename):
            continue
        if f.filename in seen:
            continue
        seen.add(f.filename)
        out.append(f.filename)
    return out


class GitHubClient:
    def __init__(
        self,
        token: str = "",
        base_url: str = GITHUB_API,
        timeout: float = 30.0,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self.token = (token or "").strip()
        self.base_url = base_url.rstrip("/")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self._client = httpx.Client(
            base_url=self.base_url, headers=headers, timeout=timeout, transport=transport
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- /repos/{full_name} -------------------------------------------------
    def get_repo(self, full_name: str) -> Dict[str, Any]:
        data = self._get(f"/repos/{full_name}")
        return data if isinstance(data, dict) else {}

    def is_private(self, full_name: str) -> bool:
        return bool(self.get_repo(full_name).get("private"))

    # -- /repos/{full_name}/pulls/{number}/files ----------------------------
    def get_pr_files(self, full_name: str, pr_number: int) -> List[PrFile]:
        out: List[PrFile] = []
        page = 1
        while True:
            data = self._get(
                f"/repos/{full_name}/pulls/{int(pr_number)}/files",
                params={"per_page": _PER_PAGE, "page": page},
            )
            if not isinstance(data, list) or not data:
                break
            out.extend(PrFile.from_raw(item) for item in data)
            if len(data) < _PER_PAGE:
                break
            page += 1
        return out

    def get_pr_changed_files(self, full_name: str, pr_number: int) -> List[str]:
        """Filtered, deduped source paths changed by the PR."""
        return filter_source_files(self.get_pr_files(full_name, pr_number))

    # -- internals ----------------------------------------------------------
    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        try:
            r = self._client.get(path, params=params)
        except httpx.HTTPError as e:  # noqa: BLE001 - normalize transport errors
            raise GitHubError(f"GitHub request failed: {e}") from e

        if r.status_code == 401:
            raise GitHubAuthError(
                "GitHub rejected the token (401). Set a valid token to access private repos."
            )
        if r.status_code == 404:
            raise GitHubError(
                f"GitHub resource not found: {path}. The repo/PR may be private or misspelled."
            )
        if r.status_code == 403:
            if r.headers.get("x-ratelimit-remaining") == "0" and not self.token:
                raise GitHubAuthError(
                    "GitHub rate limit hit without a token (403); set a token to continue."
                )
            raise GitHubError("GitHub denied the request (403): rate limit or insufficient scope.")
        if r.status_code >= 400:
            raise GitHubError(f"GitHub returned {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError as e:
            raise GitHubError("GitHub returned a non-JSON response") from e
