"""Coverage-completeness metrics for every instrumentation pipeline (Story 11.8).

Before this story only the Python path reported how much of the suite actually
produced evidence (``per_test_analyzer._coverage_completeness``). The TypeScript
and Playwright generators emitted nothing, so ``_record_instrumentation_run``
persisted all-zero metrics for those projects and
``_instrumentation_coverage_payload`` raised a spurious ``low_coverage`` warning
on every one of them.

This module gives all three paths one shape and one meaning:

``test_files_expected``/``test_files_collectable``
    What was discovered, and how much of it could be collected at all.
``test_files_scheduled``
    How many test files were actually executed this run (Python may narrow the
    set under Story 11.5; TS/Playwright may cap it).
``test_files_total``
    The denominator — the full discovered suite, never the narrowed subset, so a
    partial run stays comparable to a full one.
``test_files_instrumented``
    Files that produced evidence, counting carried-forward evidence as covered.
``missing_test_files``/``missing_count``
    The exact shortfall, so a run never silently under-covers.

``coverage_pct`` is therefore ``instrumented / total``: a capped or narrowed run
reports the truth rather than a flattering 100%.
"""
import os
from typing import Any, Dict, Iterable, Optional

#: Files named in ``missing_test_files`` are capped so a badly broken run cannot
#: serialize a megabyte of paths into the API response.
MAX_MISSING_LISTED = 50

#: The Vitest plugin keys its coverage by ``"<file> > <test name>"``.
_PLUGIN_KEY_SEPARATOR = " > "


def normalize_test_file(path: Optional[str], testbed_path: Optional[str]) -> str:
    """Repo-relative posix form of a test path or coverage key.

    Handles the three shapes that reach completeness accounting: absolute paths
    from discovery, ``./``-prefixed relative paths from coverage reports, and the
    plugin's ``"<file> > <test name>"`` keys. Only the file part is kept.
    """
    if not path:
        return ""
    p = str(path).replace("\\", "/")
    if _PLUGIN_KEY_SEPARATOR in p:
        p = p.split(_PLUGIN_KEY_SEPARATOR, 1)[0].strip()
    if testbed_path and os.path.isabs(p):
        try:
            rel = os.path.relpath(p, testbed_path)
            if not rel.startswith(".."):
                p = rel
        except ValueError:
            pass
    while p.startswith("./"):
        p = p[2:]
    return p


def compute_completeness(
    discovered: Iterable[str],
    scheduled: Iterable[str],
    covered: Iterable[str],
    *,
    covered_prefix: str = "",
    carried_forward: Optional[Iterable[str]] = None,
    testbed_path: Optional[str] = None,
    collectable: Optional[int] = None,
) -> Dict[str, Any]:
    """Build the completeness metrics dict shared by all three pipelines.

    Args:
        discovered: Every test file found in the testbed — the denominator.
        scheduled: Files actually executed this run.
        covered: Files that produced per-test coverage.
        covered_prefix: Prepended to ``covered`` entries before normalization.
            Playwright keys coverage relative to ``test_dir`` rather than the
            repo root, so it passes ``config.test_dir`` here.
        carried_forward: Files not re-run whose prior evidence was reused; they
            count as covered (Story 11.5).
        testbed_path: Root the absolute paths are relative to.
        collectable: How many discovered files could be collected at all. Pass
            ``None`` when discovery does not probe collectability (TS/Playwright
            glob for files, so everything discovered is collectable).
    """
    discovered_rel = {
        normalize_test_file(f, testbed_path) for f in (discovered or []) if f
    }
    scheduled_rel = {
        normalize_test_file(f, testbed_path) for f in (scheduled or []) if f
    }
    covered_rel = {
        normalize_test_file(os.path.join(covered_prefix, f) if covered_prefix else f,
                            testbed_path)
        for f in (covered or []) if f
    }
    carried_rel = {
        normalize_test_file(f, testbed_path) for f in (carried_forward or []) if f
    }

    # The denominator is the discovered suite. Falling back to what was scheduled
    # keeps the metric meaningful when discovery returned nothing but execution
    # still found files.
    universe = discovered_rel or scheduled_rel
    matched = sorted(universe & (covered_rel | carried_rel))
    missing = sorted(universe - (covered_rel | carried_rel))
    denom = len(universe)

    return {
        "test_files_expected": len(discovered_rel),
        "test_files_collectable": len(discovered_rel) if collectable is None else collectable,
        "test_files_scheduled": len(scheduled_rel),
        "test_files_total": denom,
        "test_files_carried_forward": len(carried_rel & universe),
        "test_files_instrumented": len(matched),
        "coverage_pct": round(100.0 * len(matched) / denom, 1) if denom else 0.0,
        "missing_test_files": missing[:MAX_MISSING_LISTED],
        "missing_count": len(missing),
    }
