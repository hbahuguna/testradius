"""Unit tests for S1: configurable selection caps + truncation reporting.

``analysis/selection.py`` is a pure module; the ``DiffParser.get_impact_tests``
unlimited-vs-capped behaviour is exercised with stub evidence so no Neo4j is
required.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ANALYSIS = _REPO_ROOT / "services" / "core" / "testsquad_core" / "analysis"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_analysis(name):
    """Load an ``analysis`` submodule by path without executing the
    ``testsquad_core`` package ``__init__`` (which pulls in Neo4j/FastAPI)."""
    core = _ANALYSIS.parent
    if "testsquad_core" not in sys.modules:
        pkg = types.ModuleType("testsquad_core")
        pkg.__path__ = [str(core)]
        sys.modules["testsquad_core"] = pkg
    if "testsquad_core.analysis" not in sys.modules:
        pkg = types.ModuleType("testsquad_core.analysis")
        pkg.__path__ = [str(_ANALYSIS)]
        sys.modules["testsquad_core.analysis"] = pkg
    full = f"testsquad_core.analysis.{name}"
    spec = importlib.util.spec_from_file_location(full, _ANALYSIS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sel():
    return _load("s1_selection", _ANALYSIS / "selection.py")


@pytest.fixture(scope="module")
def dp():
    return _load_analysis("diff_parser")


# --------------------------------------------------------------------------- #
# resolve_limit
# --------------------------------------------------------------------------- #
def test_resolve_limit_prefers_override(sel):
    assert sel.resolve_limit(5, 20, default=10) == 5


def test_resolve_limit_falls_back_to_env(sel):
    assert sel.resolve_limit(None, "20", default=10) == 20


def test_resolve_limit_skips_bad_values(sel):
    assert sel.resolve_limit("nope", None, default=10) == 10
    assert sel.resolve_limit(-3, 7, default=10) == 7


def test_resolve_limit_zero_is_unlimited(sel):
    assert sel.resolve_limit(0, default=10) == 0


# --------------------------------------------------------------------------- #
# apply_cap
# --------------------------------------------------------------------------- #
def test_apply_cap_under_limit_not_truncated(sel):
    cap = sel.apply_cap([1, 2, 3], 5)
    assert cap.selected == [1, 2, 3]
    assert cap.total == 3
    assert cap.truncated is False
    assert cap.dropped == []


def test_apply_cap_over_limit_reports_counts(sel):
    cap = sel.apply_cap([1, 2, 3, 4, 5], 2)
    assert cap.selected == [1, 2]
    assert cap.total == 5
    assert cap.truncated is True
    assert cap.dropped == [3, 4, 5]
    assert cap.selected_count == 2
    assert cap.dropped_count == 3


def test_apply_cap_unlimited_returns_full_set(sel):
    cap = sel.apply_cap([1, 2, 3], 0)
    assert cap.selected == [1, 2, 3]
    assert cap.truncated is False
    assert cap.dropped == []


def test_apply_cap_none_returns_full_set(sel):
    cap = sel.apply_cap([1, 2, 3], None)
    assert cap.selected == [1, 2, 3]
    assert cap.truncated is False


# --------------------------------------------------------------------------- #
# DiffParser.get_impact_tests: no silent slice
# --------------------------------------------------------------------------- #
def _stub_parser(dp, n_evidence=5):
    parser = dp.DiffParser(neo4j_client=object(), scorer=dp.UnifiedScorer())
    evidence = [
        dp.Evidence(
            source="coverage",
            test_name=f"t{i}",
            test_file=f"tests/test_{i}.py",
            symbol_name="foo",
            confidence=0.9,
        )
        for i in range(n_evidence)
    ]
    parser._query_evidence = lambda *a, **k: list(evidence)
    parser._query_call_graph_evidence = lambda *a, **k: []
    return parser


def test_impact_tests_default_is_unlimited(dp):
    parser = _stub_parser(dp)
    results = parser.get_impact_tests(
        [{"symbol_name": "foo", "file_path": "a.py"}], project_id=1
    )
    assert len(results) == 5


def test_impact_tests_explicit_cap_slices(dp):
    parser = _stub_parser(dp)
    results = parser.get_impact_tests(
        [{"symbol_name": "foo", "file_path": "a.py"}], project_id=1, top_k=2
    )
    assert len(results) == 2


def test_impact_tests_zero_is_unlimited(dp):
    parser = _stub_parser(dp)
    results = parser.get_impact_tests(
        [{"symbol_name": "foo", "file_path": "a.py"}], project_id=1, top_k=0
    )
    assert len(results) == 5
