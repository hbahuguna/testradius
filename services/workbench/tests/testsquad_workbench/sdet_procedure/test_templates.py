import pytest

from testsquad_workbench.sdet_procedure.templates import (
    NODE_TEMPLATES,
    get_filled_template,
)


class TestTemplates:
    def test_all_templates_have_required_keys(self):
        for tid, tmpl in NODE_TEMPLATES.items():
            assert "role" in tmpl, f"{tid} missing 'role'"
            assert "system" in tmpl, f"{tid} missing 'system'"
            assert "prompt" in tmpl, f"{tid} missing 'prompt'"

    def test_open_template(self):
        assert NODE_TEMPLATES["open"]["role"] == "agent"
        assert "Senior SDET" in NODE_TEMPLATES["open"]["system"]

    def test_user_request_template(self):
        assert NODE_TEMPLATES["user_request"]["role"] == "user"
        assert "{user_persona}" in NODE_TEMPLATES["user_request"]["system"]

    def test_generate_code_template(self):
        tmpl = NODE_TEMPLATES["generate_code"]
        assert "Playwright's modern API" in tmpl["system"]
        assert "page.waitForTimeout" in tmpl["system"]
        assert "{generated_code}" in tmpl["prompt"]

    def test_parse_requirement_has_variables(self):
        prompt = NODE_TEMPLATES["parse_requirement"]["prompt"]
        assert "{feature_name}" in prompt
        assert "{test_type}" in prompt
        assert "{complexity}" in prompt

    def test_determine_intent_mentions_test_types(self):
        system = NODE_TEMPLATES["determine_intent"]["system"]
        for tt in ("positive", "negative", "edge", "error_handling", "permission"):
            assert tt in system


class TestGetFilledTemplate:
    def test_fills_scenario_vars(self):
        result = get_filled_template(
            "determine_intent",
            node_context={},
            scenario_vars={"test_type": "positive"},
            conversation_history="",
        )
        assert "positive" in result

    def test_merges_node_context(self):
        result = get_filled_template(
            "clarify_hub",
            node_context={"clarify_decision_text": "I need more details."},
            scenario_vars={},
            conversation_history="",
        )
        assert "I need more details." in result

    def test_includes_conversation_history(self):
        result = get_filled_template(
            "parse_requirement",
            node_context={},
            scenario_vars={"feature_name": "Login", "test_type": "positive",
                          "page_type": "page", "complexity": "simple",
                          "key_actions": "click", "constraints": "None",
                          "feature_type": "auth"},
            conversation_history="USER: hello",
        )
        assert "USER: hello" in result

    def test_unknown_template_id_returns_empty(self):
        result = get_filled_template(
            "nonexistent",
            node_context={},
            scenario_vars={},
            conversation_history="",
        )
        assert result == ""

    def test_includes_page_url_suffix(self):
        result = get_filled_template(
            "user_request",
            node_context={},
            scenario_vars={"feature_name": "Login", "test_type": "positive",
                          "page_type": "page", "page_url": "https://example.com/login",
                          "feature_type": "auth"},
            conversation_history="",
        )
        assert "https://example.com/login" in result

    def test_default_values_used_when_missing(self):
        result = get_filled_template(
            "review_hub",
            node_context={},
            scenario_vars={},
            conversation_history="",
        )
        assert "accept it" in result or "review" in result.lower()
