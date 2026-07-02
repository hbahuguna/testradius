from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import ElementInfo
from .classifier import classify, ClassificationResult
from .selector_strategy import generate_selectors


@dataclass
class DescriptorField:
    name: str
    selector_type: str
    selector_value: str
    element_type: str = "GenericComponent"
    is_multiple: bool = False
    is_optional: bool = False


@dataclass
class ComponentDescriptor:
    component_type: str
    class_name: str
    root_selector: str
    fields: list[DescriptorField] = field(default_factory=list)
    confidence: float = 0.0


def _root_selector(element: ElementInfo) -> str:
    selectors = generate_selectors(element)
    if selectors:
        best = selectors[0]
        if best["type"] == "css":
            return best["value"]
        return best["value"]
    return element.css_path


def _child_relative_selector(child: ElementInfo) -> str:
    tag = child.tag
    attrs = child.attributes

    for key in ("data-testid", "data-test-id", "data-test", "data-cy"):
        val = attrs.get(key)
        if val:
            return f"[{key}='{val}']"

    aria_label = child.aria.get("aria-label") or attrs.get("aria-label")
    if aria_label:
        return f"[aria-label='{aria_label}']"

    element_id = attrs.get("id")
    if element_id:
        return f"#{element_id}"

    name = attrs.get("name")
    if name:
        return f"[name='{name}']"

    ctype = attrs.get("type")
    if ctype and ctype not in ("text",):
        return f"{tag}[type='{ctype}']"

    placeholder = attrs.get("placeholder")
    if placeholder:
        return f"{tag}[placeholder='{placeholder}']"

    return tag


def _child_field(
    child: ElementInfo,
    name: str | None = None,
) -> DescriptorField | None:
    field_selector = _child_relative_selector(child)
    field_name = name or _infer_field_name(child)
    return DescriptorField(
        name=field_name,
        selector_type="css",
        selector_value=field_selector,
        element_type=child.tag,
        is_multiple=len(child.children) > 3,
    )


def _infer_field_name(element: ElementInfo) -> str:
    text = element.text.lower().strip().replace(" ", "_")
    if text and len(text) < 30:
        return text
    element_id = element.attributes.get("id", "")
    if element_id:
        return element_id
    element_name = element.attributes.get("name", "")
    if element_name:
        return element_name
    return f"{element.tag}_{element.index}"


def build_descriptor(
    element: ElementInfo,
    classification: ClassificationResult | None = None,
) -> ComponentDescriptor:
    if classification is None:
        classification = classify(element)

    root_sel = _root_selector(element)
    class_name = _to_pascal_case(classification.component_type)
    descriptor = ComponentDescriptor(
        component_type=classification.component_type,
        class_name=class_name,
        root_selector=root_sel,
        confidence=classification.confidence,
    )

    match classification.component_type:
        case "LoginForm":
            for child in _find_children(element, "input", "button"):
                field = _child_field(child)
                if field:
                    attr_type = child.attributes.get("type", "")
                    if attr_type in ("email", "text", "username"):
                        field.name = "username_input"
                    elif attr_type == "password":
                        field.name = "password_input"
                    elif attr_type == "submit":
                        field.name = "submit_button"
                    elif attr_type == "checkbox":
                        field.name = "remember_me_checkbox"
                    descriptor.fields.append(field)

        case "DataTable":
            for child in _find_children(element, "thead", "tbody", "tr", "th"):
                field = _child_field(child)
                if field:
                    if child.tag == "th":
                        field.name = "header_cell"
                        field.is_multiple = True
                    elif child.tag == "tr":
                        field.name = "row"
                        field.is_multiple = True
                    descriptor.fields.append(field)

        case "NavBar":
            for child in _find_children(element, "a", "button", "img"):
                field = _child_field(child)
                if field:
                    if child.tag == "a" and ("brand" in child.text.lower() or not child.text):
                        field.name = "brand_link"
                    elif child.tag == "a":
                        field.name = "nav_link"
                        field.is_multiple = True
                    descriptor.fields.append(field)

        case "SearchBox":
            for child in _find_children(element, "input", "button"):
                field = _child_field(child)
                if field:
                    if child.attributes.get("type") == "search" or child.attributes.get("type") == "text":
                        field.name = "search_input"
                    elif child.attributes.get("type") == "submit" or child.tag == "button":
                        field.name = "search_button"
                    descriptor.fields.append(field)

        case "Modal":
            for child in _find_children(element, "button", "div", "h1", "h2", "h3"):
                field = _child_field(child)
                if field:
                    text = child.text.lower()
                    if "close" in text or "×" in text or "x" in text:
                        field.name = "close_button"
                    elif child.tag in ("h1", "h2", "h3"):
                        field.name = "title"
                    descriptor.fields.append(field)

        case "Card":
            for child in _find_children(element, "img", "h2", "h3", "h4", "p", "button"):
                field = _child_field(child)
                if field:
                    if child.tag == "img":
                        field.name = "image"
                    elif child.tag in ("h2", "h3", "h4"):
                        field.name = "title"
                    elif child.tag == "p":
                        field.name = "body_text"
                    elif child.tag == "button":
                        field.name = "action_button"
                        field.is_multiple = True
                    descriptor.fields.append(field)

        case "Tabs":
            for child in _find_children(element, "button", "div", "a"):
                field = _child_field(child)
                if field:
                    role = child.attributes.get("role", "")
                    if role == "tab":
                        field.name = "tab"
                        field.is_multiple = True
                    elif role == "tabpanel":
                        field.name = "tab_panel"
                        field.is_multiple = True
                    descriptor.fields.append(field)

        case "Alert":
            for child in _find_children(element, "p", "span", "button"):
                field = _child_field(child)
                if field:
                    if child.tag == "button":
                        field.name = "dismiss_button"
                    else:
                        field.name = "message"
                    descriptor.fields.append(field)

        case "Breadcrumb":
            for child in _find_children(element, "a", "li", "span"):
                field = _child_field(child)
                if field:
                    field.name = "breadcrumb_item"
                    field.is_multiple = True
                    descriptor.fields.append(field)

        case "Pagination":
            for child in _find_children(element, "a", "button", "span"):
                field = _child_field(child)
                if field:
                    text = child.text.lower()
                    if "next" in text or ">" in text:
                        field.name = "next_button"
                    elif "prev" in text or "<" in text:
                        field.name = "prev_button"
                    else:
                        field.name = "page_button"
                        field.is_multiple = True
                    descriptor.fields.append(field)

        case "Sidebar":
            for child in _find_children(element, "a", "button", "div", "nav"):
                field = _child_field(child)
                if field:
                    if child.tag == "a":
                        field.name = "menu_item"
                        field.is_multiple = True
                    descriptor.fields.append(field)

        case "FormGroup":
            for child in _find_children(element, "label", "input", "select", "textarea", "button"):
                field = _child_field(child)
                if field:
                    if child.tag == "label":
                        field.name = "label"
                    elif child.tag == "button":
                        field.name = "submit_button"
                    else:
                        field.name = child.attributes.get("name", child.tag)
                    descriptor.fields.append(field)

        case "Dropdown":
            for child in _find_children(element, "option", "li", "div"):
                field = _child_field(child)
                if field:
                    field.name = "option"
                    field.is_multiple = True
                    descriptor.fields.append(field)

        case "Accordion":
            for child in _find_children(element, "summary", "div", "button"):
                field = _child_field(child)
                if field:
                    if child.tag == "summary" or child.attributes.get("role") == "button":
                        field.name = "accordion_header"
                        field.is_multiple = True
                    else:
                        field.name = "accordion_panel"
                        field.is_multiple = True
                    descriptor.fields.append(field)

        case "Chart":
            descriptor.fields = []

        case _:
            for child in element.children[:10]:
                field = _child_field(child)
                if field:
                    descriptor.fields.append(field)

    return descriptor


def _find_children(element: ElementInfo, *tags: str) -> list[ElementInfo]:
    return [c for c in element.children if c.tag in tags]


def _to_pascal_case(name: str) -> str:
    return name
