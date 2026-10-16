"""Shared innermost-symbol attribution (Story 11.3).

Coverage data reports lines, not symbols. Given a set of symbol definitions —
each with a ``[start_line, end_line]`` span — and the covered lines, each line
is credited to its **innermost** enclosing symbol: the candidate with the
smallest span. A hit inside a method therefore credits the method only, never
its enclosing class, and Python and TypeScript attribute coverage identically.

A class-level (or module-level) symbol is still credited when a covered line
sits inside its body but outside every nested definition (e.g. class
attributes).

Story 11.7 adds :func:`attributed_line_counts`, which yields the *number* of
covered lines each owner received. ``select_innermost_owners`` is defined in
terms of it, so the selection rule and the per-symbol counts can never drift
apart.
"""
from typing import Dict, List, Sequence


def symbol_identity(sym) -> tuple:
    """A symbol's identity: bare name + span (matches the Neo4j node key)."""
    return (sym.name, sym.symbol_type, sym.start_line, sym.end_line)


# Backwards-compatible private alias (the pre-11.7 name).
_identity = symbol_identity


def _covered_line_numbers(covered_lines) -> set:
    if hasattr(covered_lines, "values"):
        all_lines = set()
        for lines in covered_lines.values():
            all_lines.update(lines)
        return all_lines
    return set(covered_lines)


def _innermost_owner(symbols: Sequence, line: int):
    innermost = None
    innermost_span = None
    for sym in symbols:
        if sym.start_line <= line <= sym.end_line:
            span = sym.end_line - sym.start_line
            if innermost is None or span < innermost_span:
                innermost = sym
                innermost_span = span
    return innermost


def attributed_line_counts(symbols: Sequence, covered_lines) -> Dict[tuple, int]:
    """Covered-line count per owned symbol, keyed by :func:`symbol_identity`.

    Args:
        symbols: objects exposing ``name``, ``symbol_type``, ``start_line`` and
            ``end_line`` — either the Python or the TypeScript ``Symbol``.
        covered_lines: the per-test coverage mapping ``{source: [line, ...]}``
            (as consumed by both resolvers) or any iterable of line numbers.

    Returns:
        ``{symbol_identity: count}`` for every symbol owning at least one
        covered line. Identities absent from the mapping were not exercised.
    """
    counts: Dict[tuple, int] = {}
    for line in _covered_line_numbers(covered_lines):
        owner = _innermost_owner(symbols, line)
        if owner is not None:
            key = symbol_identity(owner)
            counts[key] = counts.get(key, 0) + 1
    return counts


def select_innermost_owners(symbols: Sequence, covered_lines) -> List:
    """Return the symbols owning at least one covered line (innermost wins).

    Args:
        symbols: objects exposing ``name``, ``symbol_type``, ``start_line`` and
            ``end_line`` — either the Python or the TypeScript ``Symbol``.
        covered_lines: the per-test coverage mapping ``{source: [line, ...]}``
            (as consumed by both resolvers) or any iterable of line numbers.

    Returns:
        The owning symbols in their original order, each appearing at most once.
    """
    chosen = attributed_line_counts(symbols, covered_lines)
    if not chosen:
        return []

    result = []
    seen = set()
    for sym in symbols:
        key = symbol_identity(sym)
        if key in chosen and key not in seen:
            seen.add(key)
            result.append(sym)

    return result
