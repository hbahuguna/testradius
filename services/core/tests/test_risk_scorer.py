import pytest
import math
from testsquad_core.analysis.risk import RiskScorer

def test_pri_calculation_logic():
    scorer = RiskScorer()
    
    # 1. Base case: Stable, covered, internal symbol
    # LoC=10, commits=0, authors=1, coverage=1.0, is_entry=False
    # churn_factor = ln(e) = 1.0 (approx)
    # gap_factor = 2.0 - 1.0 = 1.0
    # pri = 10 * 1.0 * 1 * 1.0 * 1.0 = 10.0
    base_data = {
        "start_line": 10,
        "end_line": 20,
        "commit_count": 0,
        "author_count": 1,
        "coverage_score": 1.0,
        "is_entry_point": False
    }
    pri_base = scorer.calculate_pri(base_data)
    assert pri_base == 10.0

    # 2. Risk case: High churn, low coverage, entry point
    # LoC=10, commits=10, authors=3, coverage=0.0, is_entry=True
    # churn_factor = ln(10 + e) approx 2.54
    # gap_factor = 2.0 - 0.0 = 2.0
    # surface_boost = 2.0
    # pri = 10 * 2.54 * 3 * 2.0 * 2.0 = 304.8
    risk_data = {
        "start_line": 10,
        "end_line": 20,
        "commit_count": 10,
        "author_count": 3,
        "coverage_score": 0.0,
        "is_entry_point": True
    }
    pri_risk = scorer.calculate_pri(risk_data)
    assert pri_risk > 300
    assert pri_risk > pri_base

def test_pri_handles_missing_fields():
    scorer = RiskScorer()
    # Should not crash and use defaults
    data = {}
    pri = scorer.calculate_pri(data)
    assert pri > 0

def test_pri_loc_heuristic():
    scorer = RiskScorer()
    # Single line symbol (start=end) should have LoC 1
    data = {"start_line": 10, "end_line": 10}
    pri = scorer.calculate_pri(data)
    # 1 * ln(e) * 1 * 1 * 1 = 1
    assert pri == 1.0
