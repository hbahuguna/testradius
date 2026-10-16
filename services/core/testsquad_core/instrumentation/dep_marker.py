"""Persisted dependency-install markers (Story 11.4).

A *reused* checkout (see ``TestbedManager.clone_testbed``) must not pay for its
dependency install again. The marker records a hash of the install spec — the
commands plus the relevant lockfiles — so:

* a changed command list (e.g. a new package manager) invalidates it;
* a changed lockfile (dependencies actually moved) invalidates it;
* a failed install is simply never recorded, so the next run retries.

The marker lives inside ``node_modules`` (which is git-ignored by convention),
so it never shows up in the checkout's ``git status`` — important because the
Playwright path installs into a user's *local* working copy, not a clone.
"""
import hashlib
import os
from typing import Iterable, List, Sequence

#: Marker written into ``node_modules`` once node dependencies are installed.
NODE_DEPS_MARKER = ".tia-node-deps"

#: Lockfiles whose contents are part of the node install spec.
NODE_LOCKFILES = (
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
)


def _digest(spec: str) -> str:
    return hashlib.sha256(spec.encode("utf-8")).hexdigest()


def node_deps_spec(
    repo_path: str,
    package_manager: str,
    commands: Iterable[Sequence[str]],
) -> str:
    """A hashable description of a node install: commands + lockfile contents."""
    parts: List[str] = [f"package_manager:{package_manager}"]
    for cmd in commands:
        parts.append("cmd:" + " ".join(cmd))
    for name in NODE_LOCKFILES:
        path = os.path.join(repo_path, name)
        if os.path.isfile(path):
            try:
                with open(path, "rb") as fh:
                    parts.append(f"{name}:{hashlib.sha256(fh.read()).hexdigest()}")
            except OSError:
                parts.append(f"{name}:unreadable")
    return "\n".join(parts)


def node_marker_path(repo_path: str) -> str:
    """Marker path, kept inside ``node_modules`` to avoid polluting the repo."""
    return os.path.join(repo_path, "node_modules", NODE_DEPS_MARKER)


def node_deps_ready(
    repo_path: str,
    package_manager: str,
    commands: Iterable[Sequence[str]],
) -> bool:
    """Whether ``node_modules`` exists and matches the current install spec."""
    if not os.path.isdir(os.path.join(repo_path, "node_modules")):
        return False
    try:
        with open(node_marker_path(repo_path)) as fh:
            recorded = fh.read().strip()
    except OSError:
        return False
    return recorded == _digest(node_deps_spec(repo_path, package_manager, commands))


def record_node_deps(
    repo_path: str,
    package_manager: str,
    commands: Iterable[Sequence[str]],
) -> None:
    """Record a successful node install for a reused checkout to detect."""
    try:
        with open(node_marker_path(repo_path), "w") as fh:
            fh.write(_digest(node_deps_spec(repo_path, package_manager, commands)))
    except OSError:
        pass
