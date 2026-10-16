"""Configurable selection caps with explicit truncation reporting (S1).

The analysis pipeline used to silently drop work at hard-coded thresholds
(``len(symbols) >= 10``, ``top_k=20``). This module centralizes the limits so
they are configurable and, crucially, so callers always learn whether anything
was dropped (``truncated``) and how many items existed in total.

This module is dependency-free so it can be unit tested in isolation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

#: Defaults preserved from the previous hard-coded values; override via env.
DEFAULT_MAX_SYMBOLS = 10
DEFAULT_IMPACT_TOP_K = 20


def resolve_limit(*candidates: Any, default: int) -> int:
    """First resolvable integer wins (request override -> env -> default).

    ``None`` candidates are skipped. A non-integer or negative value falls
    through to the next candidate. ``0`` means *unlimited*.
    """
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            continue
        if value < 0:
            continue
        return value
    return default


@dataclass
class CapResult:
    """Outcome of applying a limit to a sequence of items."""

    selected: List[Any] = field(default_factory=list)
    total: int = 0
    truncated: bool = False
    dropped: List[Any] = field(default_factory=list)

    @property
    def selected_count(self) -> int:
        return len(self.selected)

    @property
    def dropped_count(self) -> int:
        return len(self.dropped)


def apply_cap(items: Sequence[Any], limit: Optional[int]) -> CapResult:
    """Return the (possibly capped) selection plus truncation metadata.

    ``limit`` of ``None`` or ``<= 0`` means *no cap* — the full set is returned
    with ``truncated=False``, so nothing is ever silently dropped.
    """
    materialized = list(items)
    total = len(materialized)
    if limit is None or limit <= 0 or total <= limit:
        return CapResult(selected=materialized, total=total, truncated=False, dropped=[])
    return CapResult(
        selected=materialized[:limit],
        total=total,
        truncated=True,
        dropped=materialized[limit:],
    )
