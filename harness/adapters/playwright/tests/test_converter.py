"""Unit tests for PlaywrightPlanConverter (STORY-E2B-003.3)."""
import ast
import json

import pytest

from harness.adapters.playwright.converter import PlaywrightPlanConverter


@pytest.fixture
def mixed_plan() -> dict:
    """Plan with a mix of automatable steps and computer_use_only steps."""
    return {
        "schema_version": "1.0",
        "plan_id": "PLAN-CONVERT-001",
        "title": "Mixed Automation Plan",
        "sut": {"base_url": "https://testradius.dev", "viewport": "1280x800"},
        "cases": [
            {
                "case_id": "TC-MIXED",
                "title": "Mixed case",
                "steps": [
                    {
                        "step_id": "S1",
                        "ordinal": 1,
                        "intent": "Navigate to login",
                        "action_type": "navigate",
                        "input": {"url": "https://testradius.dev/login"},
                    },
                    {
                        "step_id": "S2",
                        "ordinal": 2,
                        "intent": "Click login button (has explicit selector)",
                        "action_type": "click",
                        "target": {
                            "description": "Login button",
                            "hints": {"selector": "button[data-testid='login']"},
                        },
                    },
                    {
                        "step_id": "S3",
                        "ordinal": 3,
                        "intent": "Type email with placeholder hint",
                        "action_type": "type",
                        "target": {
                            "description": "Email field",
                            "hints": {"placeholder": "Email address"},
                        },
                        "input": {"text": "user@example.com"},
                    },
                    {
                        "step_id": "S4",
                        "ordinal": 4,
                        "intent": "Interact with complex canvas element (no selector)",
                        "action_type": "click",
                        "target": {
                            "description": "The small resize handle on the bottom-right of the chart widget",
                            "hints": {},
                        },
                    },
                    {
                        "step_id": "S5",
                        "ordinal": 5,
                        "intent": "Wait for animation",
                        "action_type": "wait",
                        "input": {"seconds": 2},
                    },
                    {
                        "step_id": "S6",
                        "ordinal": 6,
                        "intent": "Assert dashboard loaded",
                        "action_type": "assert",
                        "success_criteria": ["URL contains '/dashboard'", "Title contains 'Dashboard'"],
                    },
                    {
                        "step_id": "S7",
                        "ordinal": 7,
                        "intent": "Visually inspect chart rendering quality",
                        "action_type": "assert",
                        "success_criteria": [],
                    },
                ],
            }
        ],
    }


def test_converter_parses_and_reports_coverage(mixed_plan):
    converter = PlaywrightPlanConverter()
    result = converter.convert(mixed_plan)

    report = result.report
    assert report.plan_id == "PLAN-CONVERT-001"
    assert report.total_steps == 7
    # S1 navigate(url), S2 click(selector), S3 type(placeholder+text), S5 wait, S6 assert(criteria) => 5 automated
    # S4 click(no hints), S7 assert(no criteria) => 2 computer_use_only
    assert report.automated_steps == 5
    assert report.computer_use_only_steps == 2
    assert report.coverage_pct == pytest.approx(71.43, abs=0.01)

    # Check classifications
    by_id = {s.step_id: s for s in report.steps}
    assert by_id["S1"].classification == "automated"
    assert "input.url" in by_id["S1"].used_hints
    assert by_id["S2"].classification == "automated"
    assert "selector" in by_id["S2"].used_hints
    assert by_id["S3"].classification == "automated"
    assert "placeholder" in by_id["S3"].used_hints
    assert by_id["S4"].classification == "computer_use_only"
    assert any("explicit selector/hints" in r for r in by_id["S4"].reasons)
    assert by_id["S5"].classification == "automated"
    assert by_id["S6"].classification == "automated"
    assert by_id["S7"].classification == "computer_use_only"
    assert any("success_criteria" in r for r in by_id["S7"].reasons)


def test_converter_marks_locator_required_actions_without_hints_as_cuo():
    plan = {
        "plan_id": "P",
        "sut": {"base_url": "https://example.com"},
        "cases": [
            {
                "case_id": "TC",
                "steps": [
                    {"step_id": "1", "action_type": "click", "target": {"description": "something vague", "hints": {}}},
                    {"step_id": "2", "action_type": "type", "target": {"hints": {}}, "input": {"text": "hi"}},
                    {"step_id": "3", "action_type": "select", "target": {"hints": {}}, "input": {"value": "x"}},
                ],
            }
        ],
    }
    result = PlaywrightPlanConverter().convert(plan)
    assert result.report.computer_use_only_steps == 3
    assert result.report.automated_steps == 0
    assert result.coverage_pct == 0.0


def test_converter_accepts_explicit_safe_hints():
    plan = {
        "plan_id": "P",
        "sut": {"base_url": "https://example.com"},
        "cases": [
            {
                "case_id": "TC",
                "steps": [
                    {"step_id": "1", "action_type": "click", "target": {"hints": {"test_id": "submit-btn"}}},
                    {"step_id": "2", "action_type": "type", "target": {"hints": {"role": "textbox", "visible_text": ["Email"]}}, "input": {"text": "a@b.c"}},
                    {"step_id": "3", "action_type": "select", "target": {"hints": {"label": "Country"}}, "input": {"value": "US"}},
                ],
            }
        ],
    }
    result = PlaywrightPlanConverter().convert(plan)
    assert result.report.automated_steps == 3
    assert result.report.computer_use_only_steps == 0
    by_id = {s.step_id: s for s in result.report.steps}
    assert "test_id" in by_id["1"].used_hints
    assert "role+name" in by_id["2"].used_hints
    assert "label" in by_id["3"].used_hints


def test_converter_generates_valid_script_with_coverage_and_cuo(mixed_plan):
    converter = PlaywrightPlanConverter()
    result = converter.convert(mixed_plan, target_url="https://testradius.dev")

    script = result.script
    assert isinstance(script, str)
    ast.parse(script)  # valid Python

    # Coverage/report embedded
    assert "CONVERSION_REPORT" in script
    assert "PLAN-CONVERT-001" in script
    assert "AUTOMATION_COVERAGE_PCT" in script
    assert "COMPUTER_USE_ONLY" in script
    assert "computer_use_only" in script.lower()
    assert "automation_coverage_pct" in script

    # CUO handling injected
    assert 'status = "COMPUTER_USE_ONLY"' in script or "COMPUTER_USE_ONLY" in script
    assert "Gemini computer-use runner" in script


def test_converter_report_serializes_to_dict(mixed_plan):
    result = PlaywrightPlanConverter().convert(mixed_plan)
    d = result.report.to_dict()
    assert d["plan_id"] == "PLAN-CONVERT-001"
    assert d["total_steps"] == 7
    assert "coverage_pct" in d
    assert "steps" in d
    assert len(d["steps"]) == 7
    assert all("classification" in s and "reasons" in s for s in d["steps"])
    # JSON-serializable
    json.dumps(d)


def test_converter_handles_json_file_path(tmp_path, mixed_plan):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(mixed_plan), encoding="utf-8")
    result = PlaywrightPlanConverter().convert(plan_path)
    assert result.report.total_steps == 7
    ast.parse(result.script)


def test_converted_plan_annotates_steps(mixed_plan):
    result = PlaywrightPlanConverter().convert(mixed_plan)
    steps = result.converted_plan["cases"][0]["steps"]
    by_id = {s["step_id"]: s for s in steps}
    assert by_id["S2"]["automation"]["classification"] == "automated"
    assert by_id["S4"]["automation"]["classification"] == "computer_use_only"
    assert by_id["S4"]["action_type"] == "computer_use_only"
    assert by_id["S4"]["_original_action_type"] == "click"
