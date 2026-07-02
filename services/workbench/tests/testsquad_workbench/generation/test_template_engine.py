import pytest

from testsquad_workbench.generation.descriptors import (
    ComponentDescriptor,
    DescriptorField,
)
from testsquad_workbench.generation.template_engine import render_com


class TestRenderCom:
    def test_renders_class_declaration(self):
        desc = ComponentDescriptor(
            component_type="LoginForm",
            class_name="LoginForm",
            root_selector="[data-testid='login-form']",
            confidence=0.9,
            fields=[
                DescriptorField(
                    name="username_input",
                    selector_type="css",
                    selector_value="[name='email']",
                ),
                DescriptorField(
                    name="password_input",
                    selector_type="css",
                    selector_value="[name='password']",
                ),
                DescriptorField(
                    name="submit_button",
                    selector_type="css",
                    selector_value="[type='submit']",
                ),
            ],
        )
        output = render_com(desc)
        assert "class LoginForm:" in output
        assert "Component Object Model for LoginForm" in output
        assert "root_selector" in output or "data-testid" in output

    def test_renders_locator_properties(self):
        desc = ComponentDescriptor(
            component_type="NavBar",
            class_name="NavBar",
            root_selector="nav",
            confidence=0.9,
            fields=[
                DescriptorField(
                    name="brand_link",
                    selector_type="css",
                    selector_value=".brand",
                ),
                DescriptorField(
                    name="nav_link",
                    selector_type="css",
                    selector_value="a.nav-link",
                ),
            ],
        )
        output = render_com(desc)
        assert "def nav_link(self)" in output or "nav_link" in output
        assert "def brand_link(self)" in output or "brand_link" in output

    def test_renders_is_loaded(self):
        desc = ComponentDescriptor(
            component_type="GenericComponent",
            class_name="GenericComponent",
            root_selector="div",
            confidence=0.0,
        )
        output = render_com(desc)
        assert "is_loaded" in output
        assert "is_visible" in output

    def test_renders_empty_fields(self):
        desc = ComponentDescriptor(
            component_type="Chart",
            class_name="Chart",
            root_selector="canvas",
            confidence=0.5,
            fields=[],
        )
        output = render_com(desc)
        assert "class Chart:" in output
        assert "def is_loaded" in output

    def test_renders_imports(self):
        desc = ComponentDescriptor(
            component_type="Card",
            class_name="Card",
            root_selector=".card",
            confidence=0.8,
        )
        output = render_com(desc)
        assert "playwright.sync_api" in output
