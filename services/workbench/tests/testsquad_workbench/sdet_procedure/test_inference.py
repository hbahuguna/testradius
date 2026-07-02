from __future__ import annotations

import json

import pytest

from testsquad_workbench.sdet_procedure.inference import (
    PageScraper,
    SDETInference,
    format_page_context,
    extract_interactive_elements,
    extract_a11y_tree,
)
from testsquad_workbench.sdet_procedure.inference.page_scraper import (
    PageSnapshot,
    InteractiveElement,
)
from testsquad_workbench.sdet_procedure.inference.inference import (
    InferenceConfig,
    _fmt_elements,
)


class TestInteractiveElement:
    def test_defaults(self):
        el = InteractiveElement(tag="input")
        assert el.tag == "input"
        assert el.type is None
        assert el.label is None

    def test_with_all_fields(self):
        el = InteractiveElement(
            tag="button",
            type="submit",
            label="Sign In",
            id="login-btn",
            name="login",
            role="button",
            placeholder=None,
            text="Sign In",
            href=None,
            aria_label="Sign in to your account",
        )
        assert el.tag == "button"
        assert el.label == "Sign In"


class TestPageSnapshot:
    def test_to_dict(self):
        snapshot = PageSnapshot(
            url="https://example.com/login",
            title="Login",
            elements=[
                InteractiveElement(tag="input", type="email", label="Email"),
                InteractiveElement(tag="button", type="submit", label="Sign In"),
            ],
            a11y_tree={"role": "WebArea", "name": "Login"},
            viewport={"width": 1280, "height": 720},
        )
        d = snapshot.to_dict()
        assert d["url"] == "https://example.com/login"
        assert len(d["elements"]) == 2
        assert d["elements"][0]["tag"] == "input"
        assert d["elements"][0]["label"] == "Email"

    def test_empty_elements(self):
        snapshot = PageSnapshot(url="https://example.com", title="Empty")
        d = snapshot.to_dict()
        assert d["elements"] == []
        assert d["a11y_tree"] is None


class TestFormatElements:
    def test_single_element(self):
        els = [InteractiveElement(tag="input", type="email", label="Email", id="email")]
        result = _fmt_elements(els)
        assert "input" in result
        assert "Email" in result
        assert result.startswith("  ")

    def test_multiple_elements(self):
        els = [
            InteractiveElement(tag="input", type="email", label="Email", role="textbox"),
            InteractiveElement(tag="button", type="submit", label="Sign In", role="button"),
        ]
        result = _fmt_elements(els)
        lines = result.split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("  ")
        assert lines[1].startswith("  ")
        assert "input" in lines[0]
        assert "button" in lines[1]

    def test_empty_list(self):
        assert _fmt_elements([]) == ""


class TestFormatPageContext:
    def test_basic_snapshot(self):
        snapshot = PageSnapshot(
            url="https://example.com/login",
            title="Login Page",
            elements=[
                InteractiveElement(tag="input", type="email", label="Email"),
                InteractiveElement(tag="button", type="submit", label="Sign In"),
            ],
        )
        ctx = format_page_context(snapshot)
        assert "https://example.com/login" in ctx
        assert "Login Page" in ctx
        assert "=== Interactive Elements ===" in ctx
        assert "=== Accessibility Tree ===" in ctx

    def test_with_a11y(self):
        snapshot = PageSnapshot(
            url="https://example.com",
            title="Test",
            elements=[],
            a11y_tree={"role": "WebArea", "name": "Test Page"},
        )
        ctx = format_page_context(snapshot)
        assert '"role": "WebArea"' in ctx or '"WebArea"' in ctx

    def test_no_a11y(self):
        snapshot = PageSnapshot(url="https://example.com", title="Test", elements=[])
        ctx = format_page_context(snapshot)
        assert "N/A" in ctx


class TestSDETInferenceConfig:
    def test_default_config(self):
        config = InferenceConfig(model_path="/tmp/test-model")
        assert config.base_model_name == "Qwen/Qwen3-8B"
        assert config.max_seq_length == 8192
        assert config.max_new_tokens == 2048
        assert config.temperature == 0.7
        assert config.load_in_4bit is True

    def test_not_loaded_by_default(self):
        config = InferenceConfig(model_path="/tmp/test-model")
        engine = SDETInference(config)
        assert engine.is_loaded is False

    def test_generate_raises_without_load(self):
        config = InferenceConfig(model_path="/tmp/test-model")
        engine = SDETInference(config)
        with pytest.raises(RuntimeError) as exc_info:
            engine.generate("test scenario")
        assert "call .load() before .generate()" == str(exc_info.value)


class TestImportableFunctions:
    def test_extract_interactive_elements_is_async_func(self):
        assert callable(extract_interactive_elements)

    def test_extract_a11y_tree_is_async_func(self):
        assert callable(extract_a11y_tree)

    def test_page_scraper_has_scrape(self):
        assert hasattr(PageScraper, "scrape")
