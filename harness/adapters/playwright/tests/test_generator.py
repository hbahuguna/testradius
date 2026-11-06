"""Unit tests for PlaywrightScriptGenerator."""
import ast
import json
from pathlib import Path

import pytest

from harness.adapters.playwright.generator import PlaywrightScriptGenerator


@pytest.fixture
def sample_plan() -> dict:
    return {
        "schema_version": "1.0",
        "plan_id": "PLAN-PLAYWRIGHT-001",
        "title": "Authentication & Navigation Flow",
        "objective": "Verify login and navigation",
        "sut": {
            "base_url": "https://testradius.dev",
            "environment": "staging",
            "viewport": "1920x1080",
        },
        "cases": [
            {
                "case_id": "TC-LOGIN",
                "title": "Login to dashboard",
                "steps": [
                    {
                        "step_id": "S1",
                        "ordinal": 1,
                        "intent": "Go to login page",
                        "action_type": "navigate",
                        "input": {"url": "https://testradius.dev/login"},
                        "success_criteria": ["URL contains '/login'"],
                        "evidence": {"screenshot_after": True},
                    },
                    {
                        "step_id": "S2",
                        "ordinal": 2,
                        "intent": "Type email address",
                        "action_type": "type",
                        "target": {
                            "description": "Email field",
                            "hints": {"placeholder": "Enter your email", "role": "textbox"},
                        },
                        "input": {"text": "tester@testradius.dev"},
                        "evidence": {"screenshot_after": False},
                    },
                    {
                        "step_id": "S3",
                        "ordinal": 3,
                        "intent": "Click sign in",
                        "action_type": "click",
                        "target": {
                            "description": "Sign in button",
                            "hints": {"role": "button", "visible_text": ["Sign In"]},
                        },
                        "evidence": {"screenshot_after": True},
                    },
                    {
                        "step_id": "S4",
                        "ordinal": 4,
                        "intent": "Verify dashboard reached",
                        "action_type": "assert",
                        "success_criteria": [
                            "URL contains '/dashboard'",
                            "Page title contains 'Dashboard'",
                            "Visible text 'Welcome'",
                        ],
                    },
                ],
            }
        ],
    }


def test_generator_produces_valid_python_syntax(sample_plan):
    gen = PlaywrightScriptGenerator()
    script = gen.generate(sample_plan, target_url="https://testradius.dev")

    assert isinstance(script, str)
    # Validate syntax via AST parse
    parsed_ast = ast.parse(script)
    assert parsed_ast is not None

    # Check key expectations in script
    assert "async_playwright" in script
    assert "PLAYWRIGHT_BROWSERS_PATH" in script
    assert "--no-sandbox" in script
    assert "--disable-dev-shm-usage" in script
    assert "--disable-gpu" in script
    assert "PLAN-PLAYWRIGHT-001" in script
    assert "https://testradius.dev" in script
    assert "1920" in script
    assert "1080" in script
    assert "step_results.json" in script


def test_generator_handles_json_file_path(tmp_path, sample_plan):
    plan_path = tmp_path / "compiled_plan.json"
    plan_path.write_text(json.dumps(sample_plan))

    gen = PlaywrightScriptGenerator()
    script = gen.generate(plan_path)

    assert "PLAN-PLAYWRIGHT-001" in script
    ast.parse(script)


def test_generator_handles_all_action_types():
    comprehensive_plan = {
        "plan_id": "PLAN-ALL-ACTIONS",
        "sut": {"base_url": "https://example.com"},
        "cases": [
            {
                "case_id": "TC-ALL",
                "steps": [
                    {"step_id": "1", "action_type": "navigate", "input": {"url": "/home"}},
                    {"step_id": "2", "action_type": "click", "target": {"hints": {"selector": "#btn"}}},
                    {"step_id": "3", "action_type": "double_click", "target": {"hints": {"selector": ".card"}}},
                    {"step_id": "4", "action_type": "type", "target": {"hints": {"selector": "input"}}, "input": {"text": "hello"}},
                    {"step_id": "5", "action_type": "select", "target": {"hints": {"selector": "select"}}, "input": {"value": "opt1"}},
                    {"step_id": "6", "action_type": "scroll", "input": {"delta_y": 500}},
                    {"step_id": "7", "action_type": "keypress", "input": {"key": "Enter"}},
                    {"step_id": "8", "action_type": "wait", "input": {"seconds": 1}},
                    {"step_id": "9", "action_type": "assert", "success_criteria": ["URL contains '/home'"]},
                ],
            }
        ],
    }

    gen = PlaywrightScriptGenerator()
    script = gen.generate(comprehensive_plan)
    ast.parse(script)

    assert "double_click" in script
    assert "wheel" in script
    assert "keyboard.press" in script
    assert "select_option" in script
