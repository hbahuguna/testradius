"""Per-source calibration functions for TIA evidence scoring."""
import math

DEFAULT_PRIOR = 0.01

CALIBRATORS = {
    "coverage": lambda x: 0.99,
    "call_graph_1": lambda x: 0.60,
    "call_graph_2": lambda x: 0.35,
    "heuristic": lambda x: 0.40,
    "siamese": lambda x: _platt_scale(x, a=4.0, b=-2.0),
    "vector": lambda x: _platt_scale(x, a=4.0, b=-2.0),
    "llm": lambda x: max(0.3, min(0.9, 0.3 + 0.6 * x)),
    "file_fallback": lambda x: 0.05,
}


def _platt_scale(x: float, a: float = 3.0, b: float = -1.5) -> float:
    """Platt scaling: sigmoid(a * x + b)."""
    return 1.0 / (1.0 + math.exp(-(a * x + b)))


def get_calibrator(source: str):
    """Get calibrator function for given source. Returns prior if unknown."""
    return CALIBRATORS.get(source, lambda x: DEFAULT_PRIOR)
