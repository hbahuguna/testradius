"""E3/S3: canonical test counting (pure logic).

One unit for numerator and denominator: distinct collected test nodeids.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_ANALYSIS = (
    Path(__file__).resolve().parents[3]
    / "services"
    / "core"
    / "testsquad_core"
    / "analysis"
)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def counting():
    return _load("s3_counting", _ANALYSIS / "counting.py")


def _results():
    return [
        {
            "symbol_name": "a",
            "existing_tests": [
                {"test_name": "tests/x.py::test_a"},
                {"test_name": "tests/x.py::test_b[int]"},
            ],
        },
        {
            "symbol_name": "b",
            "existing_tests": [
                # reused for a second symbol — same nodeid, must count once
                {"test_name": "tests/x.py::test_a"},
            ],
        },
    ]


def test_affected_counts_distinct_nodeids(counting):
    assert counting.count_affected_nodeids(_results()) == 2


def test_affected_zero_without_results(counting):
    assert counting.count_affected_nodeids([]) == 0
    assert counting.count_affected_nodeids([{"symbol_name": "a", "existing_tests": []}]) == 0


def test_impacted_ratio_none_without_suite(counting):
    assert counting.impacted_ratio(5, None) is None
    assert counting.impacted_ratio(5, 0) is None


def test_impacted_ratio_rounds_to_4dp(counting):
    assert counting.impacted_ratio(1, 3) == 0.3333
    assert counting.impacted_ratio(2, 297) == 0.0067


def test_canonical_counts_consistent(counting):
    affected, ratio = counting.canonical_counts(_results(), 100)
    assert affected == 2
    assert ratio == 0.02
    # reduction % derives from the same pair
    assert round(1 - ratio, 4) == round((100 - affected) / 100, 4)


def test_canonical_counts_no_suite(counting):
    affected, ratio = counting.canonical_counts(_results(), 0)
    assert affected == 2
    assert ratio is None
