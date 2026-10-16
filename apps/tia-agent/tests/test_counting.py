"""E3/S3: canonical test counting — one unit (collected nodeids) for suite size,
selected count, and ratio, consistent across backend and agent.

The backend ``analyze-pr`` now returns ``total_affected_tests`` /
``total_tests_in_repo`` / ``impacted_ratio`` computed from the same
``TestSymbol.name`` nodeid universe. These tests cover the agent side: it must
consume the backend's canonical suite size and guarantee
``impacted_ratio == total_affected_tests / total_tests_in_repo``.
"""

from tia_agent.analyze import AnalyzeRunner, _suite_size
from tia_agent.config import TiaConfig
from tia_agent.radius_client import ProjectInfo


class _FakeRadius:
    base_url = "http://radius:8000"

    def __init__(self, raw):
        self.raw = raw

    def list_projects(self):
        return [ProjectInfo(id=1, name="acme/shop")]

    def analyze_pr(self, **kwargs):
        return self.raw


class _FakeGuard:
    def ensure_valid(self):
        pass

    def record_run(self, *a, **k):
        pass


def _runner(raw):
    return AnalyzeRunner(TiaConfig(), _FakeGuard(), _FakeRadius(raw))


def _nodeid_raw():
    return {
        "project_id": 1,
        "full_name": "acme/shop",
        "pr_number": 1,
        "commit_sha": "abc",
        "symbols_selected": 2,
        "tests_selected": 2,
        "total_tests_reused": 3,  # mapping count (duplicates) — NOT a nodeid unit
        "total_affected_tests": 2,
        "total_tests_in_repo": 100,
        "impacted_ratio": 0.02,
        "results": [
            {
                "symbol_name": "a",
                "existing_tests": [
                    {"test_name": "tests/x.py::test_a", "test_file": "tests/x.py", "confidence": "high"},
                    {"test_name": "tests/x.py::test_b", "test_file": "tests/x.py", "confidence": "medium"},
                ],
            },
            {
                "symbol_name": "b",
                "existing_tests": [
                    {"test_name": "tests/x.py::test_a", "test_file": "tests/x.py", "confidence": "medium"},
                ],
            },
        ],
    }


def test_affected_counts_distinct_nodeids_not_mappings():
    res = _runner(_nodeid_raw()).to_result(_nodeid_raw(), "acme/shop", 1)
    # test_a is reused by two symbols but is ONE nodeid; mapping count is 3.
    assert len(res.tests) == 2
    assert res.total_affected_tests == 2


def test_suite_size_prefers_backend_over_local(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(
        "def test_1():\n    pass\n\ndef test_2():\n    pass\n\ndef test_3():\n    pass\n"
    )
    raw = _nodeid_raw()
    # Backend reports the canonical collected-nodeid count (100); the local
    # `def test_` count would be 3.
    assert _suite_size(raw, str(tmp_path), "python") == 100
    assert _suite_size({}, str(tmp_path), "python") == 3


def test_suite_size_none_without_backend_or_checkout():
    assert _suite_size({}, None, None) is None


def test_ratio_is_numerator_over_canonical_denominator():
    res = _runner(_nodeid_raw()).to_result(_nodeid_raw(), "acme/shop", 1)
    assert res.total_tests_in_repo == 100
    assert res.total_affected_tests == 2
    assert res.impacted_ratio == round(2 / 100, 4)


def test_reduction_pct_is_internally_consistent():
    res = _runner(_nodeid_raw()).to_result(_nodeid_raw(), "acme/shop", 1)
    reduction = (res.total_tests_in_repo - res.total_affected_tests) / res.total_tests_in_repo
    assert round(reduction, 4) == round(1 - res.impacted_ratio, 4)


def test_fallback_claims_no_reduction():
    raw = {
        "symbols_selected": 0,
        "tests_selected": 0,
        "total_tests_reused": 0,
        "total_tests_in_repo": 50,
        "results": [],
    }
    res = _runner(raw).to_result(raw, "acme/shop", 2)
    assert res.fallback_used is True
    # Full suite fallback ⇒ affected == suite ⇒ ratio 1.0, no reduction claimed.
    assert res.total_affected_tests == res.total_tests_in_repo == 50
    assert res.impacted_ratio == 1.0
    assert res.safety_flag is False
