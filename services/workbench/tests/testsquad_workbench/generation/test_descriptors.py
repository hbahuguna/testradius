import pytest

from testsquad_workbench.generation.models import ElementInfo
from testsquad_workbench.generation.descriptors import (
    build_descriptor,
    ComponentDescriptor,
    DescriptorField,
)
from testsquad_workbench.generation.classifier import ClassificationResult


def _make_element(
    tag: str = "div",
    attrs: dict | None = None,
    text: str = "",
    role: str | None = None,
    aria: dict | None = None,
    children: list[ElementInfo] | None = None,
    classes: list[str] | None = None,
) -> ElementInfo:
    attributes = dict(attrs or {})
    if classes:
        attributes["class"] = classes
    return ElementInfo(
        tag=tag,
        attributes=attributes,
        text=text,
        role=role,
        aria=aria or {},
        css_path=f"body > {tag}",
        xpath=f"/html/body/{tag}",
        depth=1,
        index=1,
        children=children or [],
    )


class TestBuildDescriptor:
    def test_login_form_descriptor(self):
        element = _make_element(
            tag="form",
            children=[
                _make_element("input", {"type": "email", "name": "email"}),
                _make_element("input", {"type": "password", "name": "password"}),
                _make_element("button", {"type": "submit"}, text="Sign In"),
            ],
        )
        desc = build_descriptor(element)
        assert desc.component_type == "LoginForm"
        field_names = [f.name for f in desc.fields]
        assert "username_input" in field_names
        assert "password_input" in field_names
        assert "submit_button" in field_names

    def test_data_table_descriptor(self):
        element = _make_element(
            tag="table",
            children=[
                _make_element("thead"),
                _make_element("tbody"),
            ],
        )
        desc = build_descriptor(element)
        assert desc.component_type == "DataTable"

    def test_navbar_descriptor(self):
        element = _make_element(
            tag="nav",
            children=[
                _make_element("a", {"href": "/"}, text="Home"),
                _make_element("a", {"href": "/about"}, text="About"),
            ],
        )
        desc = build_descriptor(element)
        assert desc.component_type == "NavBar"

    def test_searchbox_descriptor(self):
        element = _make_element(
            tag="div",
            children=[
                _make_element("input", {"type": "search"}),
                _make_element("button", text="Go"),
            ],
        )
        desc = build_descriptor(element, ClassificationResult("SearchBox", 0.9, ""))
        assert desc.component_type == "SearchBox"
        field_names = [f.name for f in desc.fields]
        assert "search_input" in field_names
        assert "search_button" in field_names

    def test_modal_descriptor(self):
        element = _make_element(
            attrs={"role": "dialog"},
            children=[
                _make_element("h2", text="Confirm"),
                _make_element("button", text="Close"),
            ],
        )
        desc = build_descriptor(element)
        assert desc.component_type == "Modal"

    def test_card_descriptor(self):
        element = _make_element(
            tag="div",
            classes=["card"],
            children=[
                _make_element("img", {"src": "pic.jpg"}),
                _make_element("h3", text="Product Name"),
                _make_element("p", text="Description"),
            ],
        )
        desc = build_descriptor(element)
        assert desc.component_type == "Card"

    def test_alert_descriptor(self):
        element = _make_element(
            attrs={"role": "alert"},
            children=[
                _make_element("p", text="Warning!"),
                _make_element("button", text="Dismiss"),
            ],
        )
        desc = build_descriptor(element)
        assert desc.component_type == "Alert"

    def test_dropdown_descriptor(self):
        element = _make_element(
            tag="select",
            children=[
                _make_element("option", text="Option 1"),
                _make_element("option", text="Option 2"),
            ],
        )
        desc = build_descriptor(element)
        assert desc.component_type == "Dropdown"
        assert len(desc.fields) > 0

    def test_class_name_preserved(self):
        element = _make_element(tag="form")
        desc = build_descriptor(
            element,
            ClassificationResult("LoginForm", 0.9, ""),
        )
        assert desc.class_name == "LoginForm"

    def test_root_selector_in_descriptor(self):
        element = _make_element(
            tag="form",
            attrs={"data-testid": "login-form"},
        )
        desc = build_descriptor(element)
        assert desc.root_selector is not None
        assert "login-form" in desc.root_selector
