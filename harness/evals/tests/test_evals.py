from harness.evals.analysis import FailureAnalysis, FailureRecord, categorize_failure
from harness.evals.benchmark import BenchmarkRun, EvalReport


def test_categorize_failures():
    assert categorize_failure("Timeout waiting for selector") == "timeout"
    assert categorize_failure("Navigation failed to goto") == "navigation"
    assert categorize_failure("Element not found by selector") == "selector"
    assert categorize_failure("Network request failed") == "network"
    assert categorize_failure("Assertion expected true to be false") == "assertion"
    assert categorize_failure("Something weird happened") == "unknown"


def test_failure_analysis_summary():
    fa = FailureAnalysis()
    fa.add(FailureRecord(test_case_id="TC1", message="Timeout"))
    fa.add(FailureRecord(test_case_id="TC2", message="Timeout"))
    fa.add(FailureRecord(test_case_id="TC3", message="Selector not found"))
    s = fa.summary()
    assert s["total_failures"] == 3
    assert s["by_category"]["timeout"] == 2
    assert s["top_category"] == "timeout"


def test_eval_report():
    report = EvalReport(report_id="eval-1")
    report.add_benchmark(BenchmarkRun(run_id="r1", target="https://testradius.dev", total=9, passed=7, failed=2))
    report.add_benchmark(BenchmarkRun(run_id="r2", target="https://testradius.dev", total=9, passed=9, failed=0))
    fa = FailureAnalysis()
    fa.add(FailureRecord(test_case_id="TC1", message="Timeout"))
    report.attach_failures(fa)
    assert abs(report.pass_rate - 88.89) < 0.01
    d = report.to_dict()
    assert d["report_id"] == "eval-1"
    assert len(d["benchmarks"]) == 2
