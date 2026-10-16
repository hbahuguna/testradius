"""Coverage API payload and the ``low_coverage`` warning (Story 11.8).

Kept out of ``main.py`` so the logic is unit-testable without importing FastAPI
and PyGithub, and so the "did anyone actually measure this?" rule lives in one
place.

The rule matters because a TS/Playwright run before 11.8 recorded an all-zero
row — no metrics were ever reported. Reading that as ``coverage_pct == 0`` made
every TS/Playwright project look like a catastrophic 0% run. ``not_reported``
separates "never measured" from "measured and got 0%".
"""
from typing import Any, Dict, Mapping

#: Coverage below this % of the suite is surfaced as a warning.
LOW_COVERAGE_PCT = 95.0


def _field(row: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from a ``InstrumentationRun`` or a plain mapping."""
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def is_low_coverage(coverage_pct: float, *, not_reported: bool) -> bool:
    """Whether to warn. Unreported coverage is not a measurement, so no warning."""
    if not_reported:
        return False
    return float(coverage_pct or 0.0) < LOW_COVERAGE_PCT


def was_coverage_reported(row: Any) -> bool:
    """Whether this run's pipeline actually reported completeness metrics.

    Prefers the explicit flag written by 11.8 into ``details``. Falls back to a
    heuristic for rows recorded before it existed: a pipeline that reported has
    at least one of an expected count, a scheduled count or a missing count,
    whereas an unreported row is all zeros.
    """
    details = _field(row, "details", {}) or {}
    if isinstance(details, Mapping) and "not_reported" in details:
        return not bool(details["not_reported"])

    return bool(
        _field(row, "test_files_expected")
        or _field(row, "test_files_scheduled")
        or _field(row, "missing_count")
    )


def build_coverage_payload(row: Any) -> Dict[str, Any]:
    """Serialize an instrumentation run for ``GET .../instrumentation/coverage``."""
    details = _field(row, "details", {}) or {}
    if not isinstance(details, Mapping):
        details = {}

    coverage_pct = float(_field(row, "coverage_pct", 0.0) or 0.0)
    not_reported = not was_coverage_reported(row)
    low = is_low_coverage(coverage_pct, not_reported=not_reported)

    payload: Dict[str, Any] = {
        "project_id": _field(row, "project_id"),
        "run_id": _field(row, "id"),
        "status": _field(row, "status"),
        "edges": _field(row, "edge_count"),
        "test_files_expected": _field(row, "test_files_expected", 0),
        "test_files_collectable": _field(row, "test_files_collectable", 0),
        "test_files_scheduled": _field(row, "test_files_scheduled", 0),
        "test_files_instrumented": _field(row, "test_files_instrumented", 0),
        "coverage_pct": coverage_pct,
        "missing_count": _field(row, "missing_count", 0),
        "missing_test_files": details.get("missing_test_files", []),
        "created_at": _field(row, "created_at").isoformat()
        if _field(row, "created_at") else None,
        "not_reported": not_reported,
        "low_coverage": low,
    }
    if low:
        payload["warning"] = (
            f"coverage {coverage_pct}% is below {LOW_COVERAGE_PCT:.0f}%; "
            f"{payload['missing_count']} test file(s) produced no evidence"
        )
    return payload
