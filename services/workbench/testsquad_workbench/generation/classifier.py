from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import ElementInfo

COMPONENT_TYPES = [
    "LoginForm",
    "DataTable",
    "NavBar",
    "SearchBox",
    "Modal",
    "Card",
    "Tabs",
    "Alert",
    "Breadcrumb",
    "Pagination",
    "Sidebar",
    "FormGroup",
    "Dropdown",
    "Accordion",
    "Chart",
    "GenericComponent",
]


@dataclass
class ClassificationResult:
    component_type: str
    confidence: float
    reason: str


class ClassifierRule(Protocol):
    def __call__(self, element: ElementInfo) -> ClassificationResult | None:
        ...


def _classify_login_form(element: ElementInfo) -> ClassificationResult | None:
    if element.tag != "form":
        return None
    child_tags = [c.tag for c in element.children]
    child_attrs = [c.attributes for c in element.children]
    has_password = any(
        a.get("type") == "password" for a in child_attrs
    )
    has_username = any(
        a.get("type") in ("email", "text") and "username" in a.get("id", "").lower()
        or "username" in a.get("name", "").lower()
        for a in child_attrs
    )
    if has_password:
        return ClassificationResult("LoginForm", 0.9, "form with password input")
    return ClassificationResult("LoginForm", 0.5, "form element")


def _classify_table(element: ElementInfo) -> ClassificationResult | None:
    if element.tag == "table":
        return ClassificationResult("DataTable", 0.9, "native table element")
    if element.attributes.get("role") == "grid":
        return ClassificationResult("DataTable", 0.8, "role=grid")
    classes = " ".join(element.attributes.get("class", []))
    if "table" in classes.lower() or "grid" in classes.lower():
        return ClassificationResult("DataTable", 0.7, f"class contains table/grid")
    return None


def _classify_navbar(element: ElementInfo) -> ClassificationResult | None:
    if element.tag == "nav":
        links = [c for c in element.children if c.tag == "a"]
        if len(links) >= 2:
            return ClassificationResult("NavBar", 0.9, "nav element with multiple links")
        return ClassificationResult("NavBar", 0.7, "nav element")
    classes = " ".join(element.attributes.get("class", []))
    if "nav" in classes.lower() or "navbar" in classes.lower():
        return ClassificationResult("NavBar", 0.7, "class contains nav")
    return None


def _classify_searchbox(element: ElementInfo) -> ClassificationResult | None:
    if element.tag == "input" and element.attributes.get("type") == "search":
        return ClassificationResult("SearchBox", 0.9, "input[type=search]")
    aria_label = element.aria.get("aria-label", "").lower()
    if element.tag == "input" and ("search" in aria_label):
        return ClassificationResult("SearchBox", 0.8, "input with aria-label=search")
    classes = " ".join(element.attributes.get("class", []))
    if element.tag == "input" and "search" in classes.lower():
        return ClassificationResult("SearchBox", 0.7, "input with search class")
    return None


def _classify_modal(element: ElementInfo) -> ClassificationResult | None:
    if element.attributes.get("role") == "dialog":
        return ClassificationResult("Modal", 0.9, "role=dialog")
    classes = " ".join(element.attributes.get("class", []))
    if "modal" in classes.lower():
        return ClassificationResult("Modal", 0.7, "class contains modal")
    return None


def _classify_card(element: ElementInfo) -> ClassificationResult | None:
    if element.tag == "article":
        return ClassificationResult("Card", 0.6, "article element")
    classes = " ".join(element.attributes.get("class", []))
    if "card" in classes.lower():
        return ClassificationResult("Card", 0.8, "class contains card")
    return None


def _classify_tabs(element: ElementInfo) -> ClassificationResult | None:
    if element.attributes.get("role") == "tablist":
        return ClassificationResult("Tabs", 0.9, "role=tablist")
    classes = " ".join(element.attributes.get("class", []))
    if "tab" in classes.lower():
        return ClassificationResult("Tabs", 0.7, "class contains tab")
    return None


def _classify_alert(element: ElementInfo) -> ClassificationResult | None:
    if element.attributes.get("role") == "alert":
        return ClassificationResult("Alert", 0.9, "role=alert")
    classes = " ".join(element.attributes.get("class", []))
    if "alert" in classes.lower():
        return ClassificationResult("Alert", 0.7, "class contains alert")
    return None


def _classify_breadcrumb(element: ElementInfo) -> ClassificationResult | None:
    if element.tag == "nav":
        aria_label = element.aria.get("aria-label", "").lower()
        if "breadcrumb" in aria_label:
            return ClassificationResult("Breadcrumb", 0.95, "nav[aria-label=breadcrumb]")
    if element.tag in ("ol", "ul"):
        classes = " ".join(element.attributes.get("class", []))
        if "breadcrumb" in classes.lower():
            return ClassificationResult("Breadcrumb", 0.85, "list with breadcrumb class")
    classes = " ".join(element.attributes.get("class", []))
    if "breadcrumb" in classes.lower():
        return ClassificationResult("Breadcrumb", 0.8, "class contains breadcrumb")
    return None


def _classify_pagination(element: ElementInfo) -> ClassificationResult | None:
    if element.tag == "nav":
        aria_label = element.aria.get("aria-label", "").lower()
        if "pagination" in aria_label:
            return ClassificationResult("Pagination", 0.95, "nav[aria-label=pagination]")
    classes = " ".join(element.attributes.get("class", []))
    if "pagination" in classes.lower():
        return ClassificationResult("Pagination", 0.8, "class contains pagination")
    return None


def _classify_sidebar(element: ElementInfo) -> ClassificationResult | None:
    if element.tag == "aside":
        return ClassificationResult("Sidebar", 0.9, "aside element")
    classes = " ".join(element.attributes.get("class", []))
    if "sidebar" in classes.lower():
        return ClassificationResult("Sidebar", 0.8, "class contains sidebar")
    return None


def _classify_formgroup(element: ElementInfo) -> ClassificationResult | None:
    if element.tag == "fieldset":
        return ClassificationResult("FormGroup", 0.8, "fieldset element")
    if element.tag == "div":
        child_tags = [c.tag for c in element.children]
        label_count = child_tags.count("label")
        input_count = sum(1 for t in child_tags if t in ("input", "select", "textarea"))
        if label_count >= 1 and input_count >= 1:
            return ClassificationResult("FormGroup", 0.7, "div with labels and inputs")
    return None


def _classify_dropdown(element: ElementInfo) -> ClassificationResult | None:
    if element.tag == "select":
        return ClassificationResult("Dropdown", 0.9, "select element")
    classes = " ".join(element.attributes.get("class", []))
    if "dropdown" in classes.lower() or "select" in classes.lower():
        return ClassificationResult("Dropdown", 0.7, "class contains dropdown/select")
    return None


def _classify_accordion(element: ElementInfo) -> ClassificationResult | None:
    if element.tag == "details":
        return ClassificationResult("Accordion", 0.9, "details element")
    classes = " ".join(element.attributes.get("class", []))
    if "accordion" in classes.lower():
        return ClassificationResult("Accordion", 0.8, "class contains accordion")
    return None


def _classify_chart(element: ElementInfo) -> ClassificationResult | None:
    if element.tag in ("canvas", "svg"):
        classes = " ".join(element.attributes.get("class", []))
        if "chart" in classes.lower():
            return ClassificationResult("Chart", 0.8, f"{element.tag} with chart class")
        return ClassificationResult("Chart", 0.5, f"{element.tag} element")
    return None


RULES: list[ClassifierRule] = [
    _classify_login_form,
    _classify_table,
    _classify_navbar,
    _classify_searchbox,
    _classify_modal,
    _classify_card,
    _classify_tabs,
    _classify_alert,
    _classify_breadcrumb,
    _classify_pagination,
    _classify_sidebar,
    _classify_formgroup,
    _classify_dropdown,
    _classify_accordion,
    _classify_chart,
]


def classify(element: ElementInfo) -> ClassificationResult:
    best: ClassificationResult | None = None

    for rule in RULES:
        result = rule(element)
        if result is not None:
            if best is None or result.confidence > best.confidence:
                best = result

    if best is None:
        return ClassificationResult("GenericComponent", 0.0, "no rules matched")

    return best
