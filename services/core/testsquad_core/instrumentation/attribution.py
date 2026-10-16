"""Shared innermost-symbol attribution (Story 11.3).

Coverage data reports lines, not symbols. Given a set of symbol definitions —
each with a ``[start_line, end_line]`` span — and the covered lines, each line
is credited to its **innermost** enclosing symbol: the candidate with the
smallest span. A hit inside a method therefore credits the method only, never
its enclosing class, and Python and TypeScript attribute coverage identically.

A class-level (or module-level) symbol is still credited when a covered line
sits inside its body but outside every nested definition (e.g. class
attributes).
"""
from typing import List, Sequence


def _identity(sym) -> tuple:
    """A symbol's identity: bare name + span (matches the Neo4j node key)."""
    return (sym.name, sym.symbol_type, sym.start_line, sym.end_line)


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
    if hasattr(covered_lines, "values"):
        all_lines = set()
        for lines in covered_lines.values():
            all_lines.update(lines)
    else:
        all_lines = set(covered_lines)

    if not all_lines:
        return []

    chosen = set()
    for line in all_lines:
        innermost = None
        innermost_span = None
        for sym in symbols:
            if sym.start_line <= line <= sym.end_line:
                span = sym.end_line - sym.start_line
                if innermost is None or span < innermost_span:
                    innermost = sym
                    innermost_span = span
        if innermost is not None:
            chosen.add(_identity(innermost))

    result = []
    seen = set()
    for sym in symbols:
        key = _identity(sym)
        if key in chosen and key not in seen:
            seen.add(key)
            result.append(sym)

    return result
