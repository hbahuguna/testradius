"""Tests for calibrators and scorer modules."""
import math
import pytest
from testsquad_core.analysis.calibrators import get_calibrator, CALIBRATORS, _platt_scale, DEFAULT_PRIOR
from testsquad_core.analysis.scorer import UnifiedScorer, Evidence, ScoredTest


# ── Calibrator tests ──

def test_coverage_calibrator():
    fn = get_calibrator("coverage")
    assert fn(1.0) == pytest.approx(0.99, abs=0.001)
    assert fn(0.0) == pytest.approx(0.99, abs=0.001)


def test_heuristic_calibrator():
    fn = get_calibrator("heuristic")
    assert 0.35 <= fn(0.5) <= 0.45


def test_unknown_source_returns_prior():
    fn = get_calibrator("nonexistent")
    assert fn(0.5) == pytest.approx(DEFAULT_PRIOR, abs=0.001)


def test_vector_platt_scaling():
    fn = get_calibrator("vector")
    mid = fn(0.5)
    assert 0.45 <= mid <= 0.55
    high = fn(0.9)
    assert high > 0.8
    low = fn(0.1)
    assert low < 0.2


def test_calibrators_all_have_entries():
    for source in ["coverage", "call_graph_1", "call_graph_2", "heuristic", "vector", "siamese", "llm", "file_fallback"]:
        assert source in CALIBRATORS, f"Missing calibrator for {source}"


def test_platt_scale_sigmoid():
    assert _platt_scale(-100) == pytest.approx(0.0, abs=0.01)
    assert _platt_scale(100) == pytest.approx(1.0, abs=0.01)
    # At a=3, b=-1.5, x=0.5 → 1/(1+exp(-(1.5-1.5))) = 0.5
    assert _platt_scale(0.5, a=3.0, b=-1.5) == pytest.approx(0.5, abs=0.001)


# ── Scorer tests ──

def test_scorer_single_evidence():
    scorer = UnifiedScorer()
    evidence = [
        Evidence(source="coverage", test_name="test_get", test_file="tests/test_store.py",
                 symbol_name="get", confidence=1.0, metadata={})
    ]
    result = scorer.score("get", evidence)
    assert result.test_name == "test_get"
    assert result.test_file == "tests/test_store.py"
    assert result.symbol_name == "get"
    assert result.confidence > 0.9
    assert result.evidence_sources == ["coverage"]


def test_scorer_duplicate_weak_fuses():
    scorer = UnifiedScorer()
    evidence = [
        Evidence(source="heuristic", test_name="test_get", test_file="tests/test_store.py",
                 symbol_name="get", confidence=0.4, metadata={}),
        Evidence(source="heuristic", test_name="test_get", test_file="tests/test_store.py",
                 symbol_name="get", confidence=0.4, metadata={}),
    ]
    result = scorer.score("get", evidence)
    assert result.confidence > 0.7


def test_scorer_contradictory_dominant_wins():
    scorer = UnifiedScorer()
    evidence = [
        Evidence(source="coverage", test_name="test_get", test_file="tests/test_store.py",
                 symbol_name="get", confidence=1.0, metadata={}),
        Evidence(source="heuristic", test_name="test_get", test_file="tests/test_store.py",
                 symbol_name="get", confidence=0.3, metadata={}),
    ]
    result = scorer.score("get", evidence)
    assert result.confidence > 0.9


def test_scorer_empty_evidence_returns_prior():
    scorer = UnifiedScorer()
    result = scorer.score("get", [])
    assert result.confidence == pytest.approx(DEFAULT_PRIOR, abs=0.001)


def test_scorer_dedup_different_symbols():
    scorer = UnifiedScorer()
    e1 = Evidence(source="coverage", test_name="test_get", test_file="tests/test_store.py",
                  symbol_name="get", confidence=1.0, metadata={})
    e2 = Evidence(source="coverage", test_name="test_get", test_file="tests/test_store.py",
                  symbol_name="set", confidence=1.0, metadata={})
    r1 = scorer.score("get", [e1])
    r2 = scorer.score("set", [e2])
    assert r1.test_name == r2.test_name
    assert r1.symbol_name != r2.symbol_name


def test_scorer_ranking():
    scorer = UnifiedScorer()
    evidence = [
        Evidence(source="coverage", test_name="test_get", test_file="t.py", symbol_name="get", confidence=1.0, metadata={}),
        Evidence(source="heuristic", test_name="test_set", test_file="t.py", symbol_name="get", confidence=0.4, metadata={}),
        Evidence(source="heuristic", test_name="test_delete", test_file="t.py", symbol_name="get", confidence=0.3, metadata={}),
    ]
    from collections import defaultdict
    groups = defaultdict(list)
    for e in evidence:
        groups[(e.symbol_name, e.test_name, e.test_file)].append(e)
    results = [scorer.score(sym, ev) for (sym, _, _), ev in groups.items()]
    results.sort(key=lambda r: r.confidence, reverse=True)
    assert len(results) == 3
    assert results[0].test_name == "test_get"

    top_k = results[:2]
    assert len(top_k) == 2


def test_scorer_score_all():
    scorer = UnifiedScorer()
    evidence = [
        Evidence(source="coverage", test_name="test_get", test_file="t.py", symbol_name="get", confidence=1.0, metadata={}),
        Evidence(source="heuristic", test_name="test_set", test_file="t.py", symbol_name="get", confidence=0.4, metadata={}),
    ]
    results = scorer.score_all(evidence)
    assert len(results) == 2
    assert results[0].confidence >= results[1].confidence
