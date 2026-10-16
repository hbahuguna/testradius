"""Story 11.5 — incremental instrumentation planning.

A re-instrumentation run should not re-run a 5,000-test suite when a single file
changed. This module holds the *pure* decision: given the prior evidence graph
(production file -> test files that cover it) and the file-level diff between the
previous anchor commit and the current checkout, which tests must be re-run and
whose evidence is carried forward.

Nothing here touches Neo4j or pytest; the git helpers at the bottom are the only
side-effecting part, and they are isolated so the planner stays trivially
testable.
"""
import logging
import os
import posixpath
import subprocess
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set

logger = logging.getLogger(__name__)

#: Guard: when more than this fraction of the known production files changed,
#: the diff is "large" and we fall back to a full run — shaving a few tests off
#: a near-full run is not worth the bookkeeping.
DEFAULT_MAX_CHANGED_FRACTION = 0.5

_ENV_MAX_CHANGED_FRACTION = "TIA_INCREMENTAL_MAX_CHANGED_FRACTION"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def normalize_path(path: str, root: str = "") -> str:
    """Normalize a file path to repo-relative posix form.

    Mirrors the normalization the coverage/evidence paths already use so that a
    changed file reported by ``git`` can be matched against a ``Symbol.file_path``
    recorded earlier. Absolute paths under ``root`` become relative; absolute
    paths outside it are kept (they are matched by suffix elsewhere).
    """
    if not path:
        return ""
    p = path.replace("\\", "/").strip()
    if root:
        root_norm = root.replace("\\", "/").rstrip("/")
        if p == root_norm:
            return ""
        if p.startswith(root_norm + "/"):
            p = p[len(root_norm) + 1:]
    p = posixpath.normpath(p)
    if p == ".":
        return ""
    return p


@dataclass
class IncrementalPlan:
    """The outcome of :func:`plan_incremental_run`."""

    mode: str  # "incremental" | "full"
    reason: str
    anchor_sha: Optional[str] = None
    current_sha: Optional[str] = None
    changed_files: List[str] = field(default_factory=list)
    changed_source_files: List[str] = field(default_factory=list)
    changed_test_files: List[str] = field(default_factory=list)
    removed_test_files: List[str] = field(default_factory=list)
    #: Test files to execute this run.
    tests_to_run: List[str] = field(default_factory=list)
    #: Test files whose prior evidence stays valid (universe - tests_to_run).
    carried_forward: List[str] = field(default_factory=list)
    #: Prior tests to delete from the graph (from removed test files).
    tests_to_drop: List[str] = field(default_factory=list)
    known_source_files: List[str] = field(default_factory=list)
    fallback_fraction: float = DEFAULT_MAX_CHANGED_FRACTION

    @property
    def is_incremental(self) -> bool:
        return self.mode == "incremental"


def _full(reason: str, **kwargs) -> IncrementalPlan:
    return IncrementalPlan(mode="full", reason=reason, **kwargs)


def plan_incremental_run(
    *,
    anchor_sha: Optional[str],
    current_sha: Optional[str],
    changed_files: Optional[Iterable[str]],
    universe: Iterable[str],
    coverage_index: Mapping[str, Iterable[str]],
    fallback_fraction: Optional[float] = None,
) -> IncrementalPlan:
    """Decide what an incremental re-instrumentation run must execute.

    Args:
        anchor_sha: ``built_at_sha`` of the prior evidence (None when absent).
        current_sha: commit of the checkout being instrumented.
        changed_files: repo-relative paths changed since the anchor, or None when
            the diff could not be computed.
        universe: all test files discovered in the current checkout.
        coverage_index: prior evidence, ``{source_file: [test_file, ...]}``.
        fallback_fraction: override the large-diff guard (defaults to env/0.5).

    Returns:
        :class:`IncrementalPlan`. ``mode="full"`` means "run everything" and the
        caller must not narrow the suite.
    """
    fraction = (
        fallback_fraction if fallback_fraction is not None
        else _env_float(_ENV_MAX_CHANGED_FRACTION, DEFAULT_MAX_CHANGED_FRACTION)
    )

    # Distinguish the source files from the test files among the changed set.
    index: Dict[str, Set[str]] = {}
    for src, tests in (coverage_index or {}).items():
        src_norm = normalize_path(src)
        if not src_norm:
            continue
        index.setdefault(src_norm, set()).update(normalize_path(t) for t in tests if t)

    universe_norm: List[str] = sorted({normalize_path(t) for t in universe if t})
    universe_set = set(universe_norm)
    known_source = sorted(index)

    # Prior evidence is the precondition for narrowing anything. Checked before
    # the anchor so "never instrumented" reports as such rather than "no anchor".
    if not index:
        return _full("no_prior_evidence", fallback_fraction=fraction)

    if not anchor_sha:
        return _full("no_anchor", current_sha=current_sha, fallback_fraction=fraction)

    if not current_sha:
        return _full("no_current_sha", anchor_sha=anchor_sha, fallback_fraction=fraction)

    if changed_files is None:
        return _full(
            "diff_unavailable",
            anchor_sha=anchor_sha, current_sha=current_sha, fallback_fraction=fraction,
        )

    changed = sorted({normalize_path(p) for p in changed_files if p})

    # A changed file is a test file when it is (or was) part of the suite; every
    # other changed file is production code. Removed test files (in the graph but
    # no longer discovered) must have their stale evidence dropped.
    prior_test_files = {t for tests in index.values() for t in tests}
    test_file_set = universe_set | prior_test_files
    changed_test_files = sorted(f for f in changed if f in test_file_set)
    changed_source_files = sorted(f for f in changed if f not in test_file_set)
    removed_test_files = sorted(
        f for f in changed_test_files if f not in universe_set
    )

    # New/changed test files always re-run, so their (possibly new) assertions are
    # reflected in the evidence.
    tests_from_tests = {f for f in changed_test_files if f in universe_set}

    # Production changes re-run exactly the tests that cover them.
    tests_from_sources: Set[str] = set()
    for f in changed_source_files:
        tests_from_sources.update(index.get(f, ()))
    tests_from_sources &= universe_set

    tests_to_run = sorted(tests_from_sources | tests_from_tests)

    # Large-diff guard: not worth the bookkeeping when most files moved.
    if known_source and (len(changed_source_files) / len(known_source)) > fraction:
        return _full(
            "large_diff",
            anchor_sha=anchor_sha, current_sha=current_sha,
            changed_files=changed, changed_source_files=changed_source_files,
            changed_test_files=changed_test_files,
            known_source_files=known_source, fallback_fraction=fraction,
        )

    return IncrementalPlan(
        mode="incremental",
        reason="no_changes" if not changed else "changed_files",
        anchor_sha=anchor_sha,
        current_sha=current_sha,
        changed_files=changed,
        changed_source_files=changed_source_files,
        changed_test_files=changed_test_files,
        removed_test_files=removed_test_files,
        tests_to_run=tests_to_run,
        carried_forward=sorted(universe_set - set(tests_to_run)),
        tests_to_drop=removed_test_files,
        known_source_files=known_source,
        fallback_fraction=fraction,
    )


# --------------------------------------------------------------------------
# git helpers
# --------------------------------------------------------------------------

def _git(repo_path: str, *args: str, timeout: int = 60) -> Optional[subprocess.CompletedProcess]:
    """Run ``git -C repo_path <args>``; returns None when git is unavailable."""
    try:
        return subprocess.run(
            ["git", "-C", repo_path, *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except Exception as e:  # git missing, timeout, ...
        logger.warning(f"git {' '.join(args)} failed: {e}")
        return None


def _resolve_commit(repo_path: str, sha: str) -> bool:
    result = _git(repo_path, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
    return bool(result and result.returncode == 0)


def ensure_commit(repo_path: str, sha: Optional[str], remotes: Sequence[str] = ("origin",)) -> bool:
    """Make ``sha`` present in ``repo_path``, fetching it if necessary.

    A depth-1 clone has no history, so the prior anchor commit is normally
    absent. Fetching the single object is cheap; when the server refuses
    (``uploadpack.allowAnySHA1InWant`` disabled) we report False and the caller
    falls back to a full run.
    """
    if not sha:
        return False
    if _resolve_commit(repo_path, sha):
        return True

    for remote in remotes:
        result = _git(repo_path, "fetch", "--depth=1", remote, sha, timeout=120)
        if result and result.returncode == 0 and _resolve_commit(repo_path, sha):
            return True

    logger.info(f"Could not fetch anchor commit {sha[:12]} into {repo_path}")
    return False


def _split_lines(text: str) -> List[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def changed_files_between(
    repo_path: str,
    old_sha: Optional[str],
    new_ref: Optional[str] = None,
) -> Optional[List[str]]:
    """Repo-relative paths that differ between ``old_sha`` and ``new_ref``.

    ``new_ref=None`` diffs against the working tree (so uncommitted edits count);
    otherwise it diffs two commits. Untracked files are included because a new
    file is exactly the kind of change that must be instrumented. Returns
    ``None`` when the diff cannot be computed (e.g. the anchor is unavailable),
    which the caller treats as "fall back to a full run".
    """
    if not old_sha:
        return None
    if not ensure_commit(repo_path, old_sha):
        return None

    args = ["diff", "--name-only", "--no-renames", old_sha]
    if new_ref:
        args.append(new_ref)
    result = _git(repo_path, *args)
    if result is None or result.returncode != 0:
        return None

    changed = set(_split_lines(result.stdout))

    # Untracked files never show up in ``git diff``.
    untracked = _git(repo_path, "ls-files", "--others", "--exclude-standard")
    if untracked is not None and untracked.returncode == 0:
        changed.update(_split_lines(untracked.stdout))

    return sorted(normalize_path(p) for p in changed if p)
