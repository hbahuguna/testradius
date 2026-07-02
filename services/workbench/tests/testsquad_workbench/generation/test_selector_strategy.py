import pytest

from testsquad_workbench.generation.models import ElementInfo
from testsquad_workbench.generation.selector_strategy import (
    generate_selectors,
    pick_best_selector,
)


class TestGenerateSelectors:
    def test_data_testid_is_top_priority(self):
        element = ElementInfo(
            tag="button",
            attributes={"data-testid": "submit-btn", "id": "btn1", "class": "btn"},
            text="Submit",
            role="button",
            aria={},
            css_path="body > button",
            xpath="/html/body/button",
            depth=1,
            index=1,
        )
        selectors = generate_selectors(element)
        assert selectors[0]["strategy"] == "data-testid"
        assert selectors[0]["value"] == "[data-testid='submit-btn']"

    def test_aria_label_when_no_testid(self):
        element = ElementInfo(
            tag="button",
            attributes={},
            text="Click",
            role="button",
            aria={"aria-label": "Submit form"},
            css_path="body > button",
            xpath="/html/body/button",
            depth=1,
            index=1,
        )
        selectors = generate_selectors(element)
        assert selectors[0]["strategy"] == "aria-label"

    def test_role_with_text(self):
        element = ElementInfo(
            tag="button",
            attributes={},
            text="Save",
            role="button",
            aria={},
            css_path="body > button",
            xpath="/html/body/button",
            depth=1,
            index=1,
        )
        selectors = generate_selectors(element)
        strategies = [s["strategy"] for s in selectors]
        assert "role+text" in strategies

    def test_fallback_to_css_path(self):
        element = ElementInfo(
            tag="span",
            attributes={},
            text="Some text",
            role=None,
            aria={},
            css_path="body > div > span",
            xpath="/html/body/div/span",
            depth=2,
            index=1,
        )
        selectors = generate_selectors(element)
        last = selectors[-1]
        assert last["strategy"] == "xpath"

    def test_pick_best_selector_no_context(self):
        element = ElementInfo(
            tag="button",
            attributes={"data-testid": "login-btn"},
            text="Login",
            role="button",
            aria={},
            css_path="body > button",
            xpath="/html/body/button",
            depth=1,
            index=1,
        )
        best = pick_best_selector(element)
        assert best["strategy"] == "data-testid"
        assert best["value"] == "[data-testid='login-btn']"

    def test_multiple_data_attrs_have_first(self):
        element = ElementInfo(
            tag="div",
            attributes={"data-cy": "user-card", "data-testid": "user-card-v2"},
            text="User",
            role=None,
            aria={},
            css_path="body > div",
            xpath="/html/body/div",
            depth=1,
            index=1,
        )
        selectors = generate_selectors(element)
        assert selectors[0]["value"] == "[data-testid='user-card-v2']"

    def test_role_with_text_selector_format(self):
        element = ElementInfo(
            tag="button",
            attributes={},
            text="Delete",
            role="button",
            aria={},
            css_path="body > button",
            xpath="/html/body/button",
            depth=1,
            index=1,
        )
        selectors = generate_selectors(element)
        role_text = [s for s in selectors if s["strategy"] == "role+text"]
        assert role_text
        assert role_text[0]["type"] == "role"
        assert "Delete" in role_text[0]["value"]

    def test_id_before_css_path(self):
        element = ElementInfo(
            tag="div",
            attributes={"id": "main-content"},
            text="Content",
            role=None,
            aria={},
            css_path="body > div#main-content",
            xpath="/html/body/div",
            depth=1,
            index=1,
        )
        selectors = generate_selectors(element)
        strategies = [s["strategy"] for s in selectors]
        id_idx = strategies.index("id")
        css_idx = strategies.index("css-path")
        assert id_idx < css_idx
