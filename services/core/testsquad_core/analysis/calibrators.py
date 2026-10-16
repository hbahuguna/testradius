"""Per-source calibration functions for TIA evidence scoring."""
import math

DEFAULT_PRIOR = 0.01

CALIBRATORS = {
    # Story 11.7: coverage edges now carry a real confidence (a fraction of the
    # symbol's covered span, halved for indirect class-span attribution). A
    # fully-evidenced edge keeps the historical 0.99; a weak one slides toward
    # the COVERAGE_FLOOR instead of masquerading as certain.
    "coverage": lambda x: _coverage_scale(x),
    "call_graph_1": lambda x: 0.60,
    "call_graph_2": lambda x: 0.35,
    "heuristic": lambda x: 0.40,
    "baseline_heuristic": lambda x: max(0.3, min(0.95, x)),
    "subword_alignment": lambda x: max(0.3, min(0.90, x)),
    "import_graph": lambda x: max(0.3, min(0.90, x)),
    "directory_colocation": lambda x: max(0.3, min(0.85, x)),
    "test_call_graph": lambda x: max(0.3, min(0.88, x)),
    "neighborhood_propagation": lambda x: max(0.3, min(0.75, x)),
    "siamese": lambda x: _platt_scale(x, a=4.0, b=-2.0),
    "vector": lambda x: _platt_scale(x, a=4.0, b=-2.0),
    "llm": lambda x: max(0.3, min(0.9, 0.3 + 0.6 * x)),
    "file_fallback": lambda x: 0.05,
}

# Bounds for coverage evidence: a fully-evidenced edge is near-certain, a
# barely-covered or indirectly-attributed one is no better than a coin flip
# but never below 0.5 (the edge *was* executed, so it is better than nothing).
COVERAGE_FLOOR = 0.5
COVERAGE_CEIL = 0.99


def _coverage_scale(x: float) -> float:
    """Map an EVIDENCE edge's own confidence to an evidence probability."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        x = 1.0
    x = max(0.0, min(1.0, x))
    return COVERAGE_FLOOR + (COVERAGE_CEIL - COVERAGE_FLOOR) * x


def _platt_scale(x: float, a: float = 3.0, b: float = -1.5) -> float:
    """Platt scaling: sigmoid(a * x + b)."""
    return 1.0 / (1.0 + math.exp(-(a * x + b)))


def get_calibrator(source: str):
    """Get calibrator function for given source. Returns prior if unknown."""
    return CALIBRATORS.get(source, lambda x: x * 0.5)
