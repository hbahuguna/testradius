"""Repo mount + path normalization for the bundled backend (E3/T2).

The user's repo is bind-mounted into the core container at
``/workdir/<repo-name>`` and advertised to the backend via
``TESTRADIUS_LOCAL_PATH``. Backend responses echo absolute container paths, so
these helpers translate both ways:

    host path  <->  container path  <->  repo-relative path
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

WORKDIR_PREFIX = "/workdir"
#: Legacy mount prefixes the core-ml dev stack may still emit.
LEGACY_PREFIXES = ("/testradius",)

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_name(name: str) -> str:
    cleaned = _UNSAFE.sub("-", name).strip("-._")
    return cleaned or "repo"


@dataclass(frozen=True)
class RepoMount:
    name: str
    host_path: str
    container_path: str

    def to_dict(self) -> dict:
        return {"name": self.name, "host_path": self.host_path,
                "container_path": self.container_path}


def repo_mount(repo_path: str | os.PathLike) -> RepoMount:
    host = os.path.abspath(os.path.expanduser(str(repo_path)))
    name = sanitize_name(Path(host).name)
    return RepoMount(name=name, host_path=host, container_path=f"{WORKDIR_PREFIX}/{name}")


def normalize_repo_path(path: str, mount: Optional[RepoMount] = None) -> str:
    """Strip container/legacy prefixes so a path is repo-relative."""
    if not path:
        return ""
    p = str(path).replace("\\", "/")

    prefixes = []
    if mount is not None:
        prefixes.append(mount.container_path)
    prefixes.extend(LEGACY_PREFIXES)

    for prefix in prefixes:
        prefix = prefix.rstrip("/")
        if not prefix:
            continue
        if p == prefix:
            p = ""
            break
        if p.startswith(prefix + "/"):
            p = p[len(prefix) + 1:]
            break

    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def to_container_path(path: str | os.PathLike, mount: RepoMount) -> str:
    """Map a host path (inside the repo) to its path inside the container."""
    raw = str(path)
    if not os.path.isabs(raw):
        rel = normalize_repo_path(raw, mount)
        return f"{mount.container_path}/{rel}" if rel else mount.container_path
    p = os.path.abspath(os.path.expanduser(raw))
    root = mount.host_path.rstrip("/")
    if p == root:
        return mount.container_path
    if p.startswith(root + "/"):
        rel = os.path.relpath(p, root)
        return f"{mount.container_path}/{rel}".replace(os.sep, "/")
    rel = normalize_repo_path(p, mount)
    return f"{mount.container_path}/{rel}" if rel else mount.container_path
