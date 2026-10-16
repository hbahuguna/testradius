"""E5/O1: output schema, run commands, and the >30% safety cap."""

import json

from tia_agent.analyze import SAFETY_RATIO, AnalyzeRunner, TiaResult
from tia_agent.config import TiaConfig
from tia_agent.output import OUTPUT_SCHEMA, SCHEMA_VERSION, build_run_commands, validate_output
from tia_agent.output.schema import require_valid_output
from tia_agent.radius_client import ProjectInfo
from tia_agent.tools.fs import count_test_cases
from tia_agent.tools.language import detect_js_test_runner


# ---------------------------------------------------------------------------
# fakes (mirrors test_f1_evidence)
# ---------------------------------------------------------------------------

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


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _evidence_raw(test_file, test_name="test_1"):
    return {
        "pr_files_analyzed": 1,
        "pr_files": ["src/a.py"],
        "symbols_selected": 1,
        "tests_selected": 1,
        "total_tests_reused": 1,
        "results": [
            {
                "symbol_name": "f",
                "existing_tests": [{"test_name": test_name, "test_file": test_file}],
            }
        ],
    }


# ---------------------------------------------------------------------------
# run commands
# ---------------------------------------------------------------------------

def _t(language, file, name="x"):
    return {"file": file, "name": name, "nodeid": f"{file}::{name}",
            "language": language, "reason": "sym"}


def test_run_commands_python_uses_pytest_nodeid():
    cmds = build_run_commands([_t("python", "tests/test_a.py", "test_1")])
    assert cmds == ["pytest tests/test_a.py::test_1"]


def test_run_commands_playwright_spec_uses_playwright():
    cmds = build_run_commands([_t("typescript", "tests/home.spec.ts", "shows home")])
    assert cmds == ["npx playwright test tests/home.spec.ts"]


def test_run_commands_runner_override_vitest_and_jest():
    tests = [_t("typescript", "src/a.test.ts"), _t("typescript", "src/b.test.ts")]
    assert build_run_commands(tests, runner="vitest") == [
        "npx vitest run src/a.test.ts",
        "npx vitest run src/b.test.ts",
    ]
    assert build_run_commands(tests, runner="jest") == [
        "npx jest src/a.test.ts",
        "npx jest src/b.test.ts",
    ]


def test_run_commands_dedupes_same_file():
    tests = [_t("typescript", "tests/home.spec.ts", "a"),
             _t("typescript", "tests/home.spec.ts", "b")]
    assert build_run_commands(tests) == ["npx playwright test tests/home.spec.ts"]


def test_run_commands_skips_unknown_language():
    assert build_run_commands([_t("unknown", "x.rb")]) == []


def test_detect_js_test_runner(tmp_path):
    _write(tmp_path / "package.json",
           json.dumps({"devDependencies": {"vitest": "1.0.0"}}))
    assert detect_js_test_runner(str(tmp_path)) == "vitest"
    _write(tmp_path / "package.json",
           json.dumps({"devDependencies": {"@playwright/test": "1.0.0"}}))
    assert detect_js_test_runner(str(tmp_path)) == "playwright"
    _write(tmp_path / "package.json", json.dumps({"dependencies": {}}))
    assert detect_js_test_runner(str(tmp_path)) is None


def test_count_test_cases_python_and_fallback(tmp_path):
    _write(tmp_path / "tests" / "test_a.py",
           "def test_1():\n    pass\n\ndef test_2():\n    pass\n")
    assert count_test_cases(str(tmp_path), "python") == 2
    # No recognisable cases -> falls back to the number of test files.
    _write(tmp_path / "tests" / "test_b.py", "print('hi')\n")
    assert count_test_cases(str(tmp_path), "python") == 2  # still 2 files, 2 cases


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------

def test_to_dict_satisfies_schema(tmp_path):
    _write(tmp_path / "tests" / "test_a.py", "def test_1():\n    pass\n")
    result = _runner(_evidence_raw("tests/test_a.py")).to_result(
        _evidence_raw("tests/test_a.py"), "acme/shop", 7, repo_path=str(tmp_path))
    data = result.to_dict()
    assert data["schema_version"] == SCHEMA_VERSION
    assert validate_output(data) == []
    assert set(data) == set(OUTPUT_SCHEMA["properties"])
    assert all(k in data for k in OUTPUT_SCHEMA["required"])


def test_require_valid_output_raises_on_bad_confidence():
    data = TiaResult(
        tia_run_id="r", repo="a/b", pr_number=1, files_analyzed=0, symbols_selected=0,
        tests_selected=0, total_affected_tests=0, total_tests_in_repo=None,
        fallback_used=False, fallback_reason=None, confidence="meh",
    ).to_dict()
    errors = validate_output(data)
    assert any("confidence" in e for e in errors)
    try:
        require_valid_output(data)
    except ValueError as exc:
        assert "confidence" in str(exc)
    else:
        raise AssertionError("expected OutputSchemaError")


def test_validate_output_rejects_missing_and_unknown_fields():
    good = TiaResult(
        tia_run_id="r", repo="a/b", pr_number=1, files_analyzed=0, symbols_selected=0,
        tests_selected=0, total_affected_tests=0, total_tests_in_repo=None,
        fallback_used=False, fallback_reason=None, confidence="low",
    ).to_dict()
    assert validate_output(good) == []

    missing = {k: v for k, v in good.items() if k != "repo"}
    assert any("repo" in e for e in validate_output(missing))

    extra = dict(good, surprise=1)
    assert any("surprise" in e for e in validate_output(extra))

    bad_ratio = dict(good, impacted_ratio=1.5)
    assert any("impacted_ratio" in e for e in validate_output(bad_ratio))


def test_schema_requires_per_test_confidence_and_reason(tmp_path):
    # V2: no opaque selections — the contract requires a non-empty reason and
    # a known confidence on every selected test.
    _write(tmp_path / "tests" / "test_a.py", "def test_1():\n    pass\n")
    result = _runner(_evidence_raw("tests/test_a.py")).to_result(
        _evidence_raw("tests/test_a.py"), "acme/shop", 7, repo_path=str(tmp_path))
    data = result.to_dict()
    assert validate_output(data) == []
    assert all("reason" in t and "confidence" in t for t in data["tests"])

    def _mutate(**overrides):
        tests = [dict(data["tests"][0], **overrides)]
        return dict(data, tests=tests)

    no_conf = _mutate()
    no_conf["tests"][0].pop("confidence")
    assert any("confidence" in e for e in validate_output(no_conf))

    blank_reason = _mutate(reason="   ")
    assert any("reason" in e for e in validate_output(blank_reason))

    bad_conf = _mutate(confidence="maybe")
    assert any("confidence" in e for e in validate_output(bad_conf))


# ---------------------------------------------------------------------------
# safety cap
# ---------------------------------------------------------------------------

def test_safety_flag_fires_above_30_percent(tmp_path):
    # 3 cases in the suite, 1 affected -> 33% > 30%.
    _write(tmp_path / "tests" / "test_a.py",
           "def test_1():\n    pass\n\ndef test_2():\n    pass\n\ndef test_3():\n    pass\n")
    res = _runner({}).to_result(
        _evidence_raw("tests/test_a.py"), "acme/shop", 9, repo_path=str(tmp_path),
        language="python")
    info = res.to_dict()
    assert info["total_tests_in_repo"] == 3
    assert info["total_affected_tests"] == 1
    assert info["impacted_ratio"] > SAFETY_RATIO
    assert res.safety_flag is True
    assert info["run_commands"] == ["pytest tests/test_a.py::test_1"]


def test_safety_flag_quiet_below_30_percent(tmp_path):
    defs = "".join(f"def test_{i}():\n    pass\n\n" for i in range(20))
    _write(tmp_path / "tests" / "test_b.py", defs)
    res = _runner({}).to_result(
        _evidence_raw("tests/test_b.py"), "acme/shop", 10, repo_path=str(tmp_path),
        language="python")
    assert res.total_tests_in_repo == 20
    assert res.impacted_ratio < SAFETY_RATIO
    assert res.safety_flag is False


def test_print_result_json_validates(capsys):
    from tia_agent.interfaces.cli import _print_result

    res = _runner({}).to_result(_evidence_raw("tests/test_a.py"), "acme/shop", 3)
    assert _print_result(res, True) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema_version"] == SCHEMA_VERSION
    assert validate_output(out) == []


def test_print_result_human_shows_suite_and_safety(capsys):
    from tia_agent.interfaces.cli import _print_result

    res = TiaResult(
        tia_run_id="r", repo="a/b", pr_number=1, files_analyzed=2, symbols_selected=3,
        tests_selected=3, total_affected_tests=4, total_tests_in_repo=10,
        fallback_used=False, fallback_reason=None, confidence="high",
        safety_flag=True, impacted_ratio=0.4,
    )
    assert _print_result(res, False) == 0
    out = capsys.readouterr().out
    assert "files analyzed : 2" in out
    assert "suite size     : 10 tests (40% impacted)" in out
    assert "[safety]" in out


def test_safety_flag_suppressed_on_fallback(tmp_path):
    _write(tmp_path / "tests" / "test_a.py", "def test_1():\n    pass\n")
    raw = {
        "pr_files_analyzed": 1,
        "pr_files": ["src/new.py"],
        "symbols_selected": 0,
        "tests_selected": 0,
        "total_tests_reused": 0,
        "results": [],
    }
    res = _runner(raw).to_result(raw, "acme/shop", 11, repo_path=str(tmp_path), language="python")
    assert res.fallback_used is True
    assert res.safety_flag is False
