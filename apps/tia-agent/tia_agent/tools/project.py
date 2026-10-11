"""Resolve a GitHub repo (owner/repo) to a TestRadius project_id.

Projects are matched by name. The name is typically the repo full_name
("owner/repo"); we also accept a project whose name equals the repo basename,
or any project whose name is a suffix of the full_name.
"""

from __future__ import annotations

from ..errors import AnalysisError, BackendError
from ..radius_client import ProjectInfo, RadiusClient


def resolve_project_for_repo(radius: RadiusClient, repo: str) -> ProjectInfo:
    repo = repo.strip().rstrip("/")
    normalized = repo
    if normalized.startswith(("https://", "http://", "git@", "git://")):
        normalized = _parse_remote(normalized)

    try:
        projects = radius.list_projects()
    except BackendError:
        raise

    candidates = []
    for p in projects:
        pname = (p.name or "").strip("/")
        if pname == normalized or pname.endswith(f"/{normalized}") or normalized.endswith(f"/{pname}"):
            candidates.append(p)

    if not candidates:
        raise AnalysisError(
            f"No TestRadius project matches '{repo}'. "
            "Run instrumentation first to register the repo and collect symbol evidence.",
        )

    # Prefer an exact match; else the longest name (most specific).
    candidates.sort(key=lambda p: len(p.name), reverse=True)
    return candidates[0]


def _parse_remote(url: str) -> str:
    url = url.rstrip(".git")
    if "://" in url:
        return url.split("://", 1)[1].lstrip("/")
    # scp-like git@github.com:owner/repo
    if "@" in url and ":" in url:
        return url.split(":", 1)[1]
    return url