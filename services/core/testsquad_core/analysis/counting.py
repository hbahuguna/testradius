"""S3: canonical test counting.

A "test" is a **collected pytest nodeid** — the unit used consistently for both
the numerator (selected tests) and the denominator (suite size), so the impact
ratio and the reduction percentage are internally consistent.

``TestSymbol.name`` is the full nodeid (``path::Class::method``), so the set of
distinct names is already the distinct-nodeid count.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def count_affected_nodeids(results: List[Dict[str, Any]]) -> int:
    """Distinct selected test nodeids across every symbol's mappings.

    Reusing one test for several changed symbols counts it once (a nodeid is a
    nodeid), unlike a raw mapping/edge count.
    """
    return len(
        {
            t["test_name"]
            for result in results
            for t in result.get("existing_tests", [])
        }
    )


def impacted_ratio(affected: int, suite_size: Optional[int]) -> Optional[float]:
    """``affected / suite_size`` rounded to 4 dp, or ``None`` without a suite."""
    if not suite_size:
        return None
    return round(affected / suite_size, 4)


def canonical_counts(
    results: List[Dict[str, Any]],
    suite_size: Optional[int],
) -> Tuple[int, Optional[float]]:
    """Return ``(total_affected_tests, impacted_ratio)`` in one unit."""
    affected = count_affected_nodeids(results)
    return affected, impacted_ratio(affected, suite_size)
