"""Confidence gradation for ``[:EVIDENCE]`` edges (Story 11.7).

Every coverage edge used to be written with ``confidence: 1.0``, so ranking
could not tell a fully-exercised function from a class that merely had one line
touched. The edge confidence is now derived from two *measured* facts:

``covered_line_count``
    How many covered lines were attributed to the symbol (innermost wins).
``coverage_kind``
    ``line`` for a function/method attributed from its own covered lines,
    ``branch`` for branch/arc coverage (reserved — the Python extractor
    currently emits line coverage only), and ``inferred`` when the attribution
    is indirect — today, a class credited through a line in its body that lies
    outside every nested definition.

Formula::

    span       = max(1, end_line - start_line + 1)
    ratio      = clamp(covered_line_count / span, 0, 1)
    weight     = INFERRED_WEIGHT (0.5) if coverage_kind == "inferred" else 1.0
    confidence = round(ratio * weight, 4)

A ``None`` count means "no coverage metadata was recorded" — the pre-11.7
callers that only ever passed a symbol's span. It is treated as a fully-covered
symbol so their behaviour (and every edge they wrote) is preserved at 1.0.
"""
from typing import Optional

LINE = "line"
BRANCH = "branch"
INFERRED = "inferred"

# How hard an indirect (class-span) attribution is discounted. Documented in
# the story and the runbook: never a guess, always this fixed factor.
INFERRED_WEIGHT = 0.5


def kind_for_symbol(symbol_type: str) -> str:
    """The coverage kind for a directly-attributed symbol.

    Only a class is discounted: it is credited through a line in its body that
    sits outside every nested definition, which is evidence *about the class*
    rather than a measured callable entry point.
    """
    return INFERRED if symbol_type == "class" else LINE


def symbol_span(start_line, end_line) -> int:
    """Line count of a symbol's ``[start_line, end_line]`` span (>= 1)."""
    return max(1, int(end_line) - int(start_line) + 1)


def normalized_line_count(
    covered_line_count: Optional[int], start_line, end_line
) -> int:
    """The ``covered_line_count`` to store on the edge.

    ``None`` (no metadata — a legacy caller) widens to the whole span so the
    symbol reads as fully covered. A real count is clamped to the span.
    """
    span = symbol_span(start_line, end_line)
    if covered_line_count is None:
        return span
    try:
        count = int(covered_line_count)
    except (TypeError, ValueError):
        return span
    return max(0, min(count, span))


def confidence_for(
    covered_line_count: Optional[int],
    start_line,
    end_line,
    coverage_kind: Optional[str] = None,
) -> float:
    """The documented confidence for one ``[:EVIDENCE]`` edge."""
    span = symbol_span(start_line, end_line)
    count = normalized_line_count(covered_line_count, start_line, end_line)
    ratio = count / span
    weight = INFERRED_WEIGHT if (coverage_kind or LINE) == INFERRED else 1.0
    return round(ratio * weight, 4)
