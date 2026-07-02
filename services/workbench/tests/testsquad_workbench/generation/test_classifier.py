import pytest

from testsquad_workbench.generation.models import ElementInfo
from testsquad_workbench.generation.classifier import (
    classify,
    ClassificationResult,
    COMPONENT_TYPES,
)


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


class TestClassify:
    def test_login_form_with_password(self):
        element = _make_element(
            tag="form",
            children=[
                _make_element("input", {"type": "email", "id": "username"}),
                _make_element("input", {"type": "password"}),
            ],
        )
        result = classify(element)
        assert result.component_type == "LoginForm"
        assert result.confidence >= 0.5

    def test_data_table_native(self):
        element = _make_element(tag="table")
        result = classify(element)
        assert result.component_type == "DataTable"

    def test_data_table_role_grid(self):
        element = _make_element(attrs={"role": "grid"})
        result = classify(element)
        assert result.component_type == "DataTable"

    def test_navbar_nav_tag(self):
        element = _make_element(
            tag="nav",
            children=[
                _make_element("a", {"href": "/"}),
                _make_element("a", {"href": "/about"}),
            ],
        )
        result = classify(element)
        assert result.component_type == "NavBar"

    def test_searchbox_input_type(self):
        element = _make_element("input", {"type": "search"})
        result = classify(element)
        assert result.component_type == "SearchBox"

    def test_searchbox_aria_label(self):
        element = _make_element("input", aria={"aria-label": "Search"})
        result = classify(element)
        assert result.component_type == "SearchBox"

    def test_modal_role_dialog(self):
        element = _make_element(attrs={"role": "dialog"})
        result = classify(element)
        assert result.component_type == "Modal"

    def test_card_class(self):
        element = _make_element(classes=["card", "product"])
        result = classify(element)
        assert result.component_type == "Card"

    def test_tabs_role_tablist(self):
        element = _make_element(attrs={"role": "tablist"})
        result = classify(element)
        assert result.component_type == "Tabs"

    def test_alert_role(self):
        element = _make_element(attrs={"role": "alert"})
        result = classify(element)
        assert result.component_type == "Alert"

    def test_breadcrumb_nav_aria(self):
        element = _make_element(tag="nav", aria={"aria-label": "breadcrumb"})
        result = classify(element)
        assert result.component_type == "Breadcrumb"

    def test_breadcrumb_class(self):
        element = _make_element(tag="ol", classes=["breadcrumb"])
        result = classify(element)
        assert result.component_type == "Breadcrumb"

    def test_pagination_nav_aria(self):
        element = _make_element(tag="nav", aria={"aria-label": "pagination"})
        result = classify(element)
        assert result.component_type == "Pagination"

    def test_pagination_class(self):
        element = _make_element(classes=["pagination"])
        result = classify(element)
        assert result.component_type == "Pagination"

    def test_sidebar_aside(self):
        element = _make_element(tag="aside")
        result = classify(element)
        assert result.component_type == "Sidebar"

    def test_sidebar_class(self):
        element = _make_element(classes=["sidebar"])
        result = classify(element)
        assert result.component_type == "Sidebar"

    def test_formgroup_fieldset(self):
        element = _make_element(tag="fieldset")
        result = classify(element)
        assert result.component_type == "FormGroup"

    def test_formgroup_div_with_labels(self):
        element = _make_element(
            children=[
                _make_element("label", {"for": "email"}),
                _make_element("input", {"type": "email"}),
            ]
        )
        result = classify(element)
        assert result.component_type == "FormGroup"

    def test_dropdown_select(self):
        element = _make_element(tag="select")
        result = classify(element)
        assert result.component_type == "Dropdown"

    def test_dropdown_class(self):
        element = _make_element(classes=["dropdown"])
        result = classify(element)
        assert result.component_type == "Dropdown"

    def test_accordion_details(self):
        element = _make_element(tag="details")
        result = classify(element)
        assert result.component_type == "Accordion"

    def test_accordion_class(self):
        element = _make_element(classes=["accordion"])
        result = classify(element)
        assert result.component_type == "Accordion"

    def test_chart_canvas(self):
        element = _make_element(tag="canvas")
        result = classify(element)
        assert result.component_type == "Chart"

    def test_chart_svg_with_class(self):
        element = _make_element(tag="svg", classes=["chart"])
        result = classify(element)
        assert result.component_type == "Chart"

    def test_generic_component_fallback(self):
        element = _make_element(tag="span", text="Hello")
        result = classify(element)
        assert result.component_type == "GenericComponent"

    def test_classification_highest_confidence_wins(self):
        element = _make_element(
            tag="form",
            attrs={"role": "dialog"},
            children=[
                _make_element("input", {"type": "password"}),
            ],
        )
        result = classify(element)
        assert result.component_type in ("LoginForm", "Modal")
        assert result.confidence > 0.5

    def test_all_component_types_covered(self):
        covered = {
            "LoginForm", "DataTable", "NavBar", "SearchBox",
            "Modal", "Card", "Tabs", "Alert", "Breadcrumb",
            "Pagination", "Sidebar", "FormGroup", "Dropdown",
            "Accordion", "Chart", "GenericComponent",
        }
        assert set(COMPONENT_TYPES) == covered
