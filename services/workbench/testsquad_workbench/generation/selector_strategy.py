from __future__ import annotations

import re
from typing import Protocol

from .models import ElementInfo

SELECTOR_PRIORITY: list[str] = [
    "data-testid",
    "aria-label",
    "role+text",
    "id",
    "css-path",
    "xpath",
]


def _sanitize(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9\-_ ]", "", text).strip()


def generate_selectors(element: ElementInfo) -> list[dict[str, str]]:
    selectors: list[dict[str, str]] = []

    attrs = element.attributes
    aria = element.aria

    for key in ("data-testid", "data-test-id", "data-test", "data-cy"):
        val = attrs.get(key)
        if val:
            selectors.append({"type": "css", "value": f"[{key}='{val}']", "strategy": key})
            break

    aria_label = aria.get("aria-label") or attrs.get("aria-label")
    if aria_label:
        label = _sanitize(aria_label)
        selectors.append({"type": "css", "value": f"[aria-label='{label}']", "strategy": "aria-label"})

    if element.role and element.text:
        role = element.role
        text = _sanitize(element.text)
        selectors.append({
            "type": "role",
            "value": f"role={role}[name='{text}']",
            "strategy": "role+text",
        })
        selectors.append({
            "type": "text",
            "value": f"text={text}",
            "strategy": "text",
        })

    element_id = attrs.get("id")
    if element_id:
        selectors.append({"type": "css", "value": f"#{element_id}", "strategy": "id"})

    if element.css_path:
        selectors.append({
            "type": "css",
            "value": element.css_path,
            "strategy": "css-path",
        })

    if element.xpath:
        selectors.append({"type": "xpath", "value": element.xpath, "strategy": "xpath"})

    return selectors


def pick_best_selector(
    element: ElementInfo,
    all_elements: list[ElementInfo] | None = None,
) -> dict[str, str]:
    selectors = generate_selectors(element)
    if not selectors:
        return {"type": "css", "value": element.css_path, "strategy": "fallback"}

    for sel in selectors:
        if all_elements is None:
            return sel
        if _is_unique(sel, element, all_elements):
            return sel

    return selectors[-1]


def _is_unique(
    selector: dict[str, str],
    element: ElementInfo,
    all_elements: list[ElementInfo],
) -> bool:
    count = 0
    for other in all_elements:
        if _selector_matches(selector, other):
            count += 1
        if count > 1:
            return False
    return count == 1


def _selector_matches(selector: dict[str, str], element: ElementInfo) -> bool:
    strategy = selector["strategy"]
    value = selector["value"]

    if strategy in ("data-testid", "data-test-id", "data-test", "data-cy"):
        test_id = element.attributes.get(strategy)
        return test_id is not None and test_id in value

    if strategy == "aria-label":
        return element.aria.get("aria-label") == _extract_aria_value(value)

    if strategy == "role+text":
        return element.role is not None and element.text == _extract_text_value(value)

    if strategy == "id":
        expected = value.lstrip("#")
        return element.attributes.get("id") == expected

    if strategy == "css-path":
        return element.css_path == value

    if strategy == "xpath":
        return element.xpath == value

    return False


def _extract_aria_value(selector: str) -> str:
    match = re.match(r"\[aria-label='([^']+)'\]", selector)
    return match.group(1) if match else ""


def _extract_text_value(selector: str) -> str:
    match = re.match(r"role=\w+\[name='([^']+)'\]", selector)
    return match.group(1) if match else ""


def generate_relative_selectors(element: ElementInfo) -> list[dict[str, str]]:
    """Generate candidate selectors relative to a parent root context.

    Returns list of {strategy, selector, type} where selector is a relative
    CSS selector meant to be scoped under a parent locator.
    """
    candidates: list[dict[str, str]] = []
    attrs = element.attributes
    tag = element.tag

    for key in ("data-testid", "data-test-id", "data-test", "data-cy"):
        val = attrs.get(key)
        if val:
            candidates.append({"strategy": key, "selector": f"[{key}='{val}']", "type": "css"})
            break

    aria_label = element.aria.get("aria-label") or attrs.get("aria-label")
    if aria_label:
        label = _sanitize(aria_label)
        candidates.append({"strategy": "aria-label", "selector": f"[aria-label='{label}']", "type": "css"})

    element_id = attrs.get("id")
    if element_id:
        candidates.append({"strategy": "id", "selector": f"#{element_id}", "type": "css"})

    name = attrs.get("name")
    if name:
        candidates.append({"strategy": "name", "selector": f"[name='{name}']", "type": "css"})

    placeholder = attrs.get("placeholder")
    if placeholder:
        candidates.append({"strategy": "placeholder", "selector": f"[placeholder='{placeholder}']", "type": "css"})

    role = attrs.get("role")
    if role:
        candidates.append({"strategy": "role", "selector": f"[role='{role}']", "type": "css"})

    ctype = attrs.get("type")
    if ctype and ctype not in ("text",):
        candidates.append({"strategy": "type", "selector": f"{tag}[type='{ctype}']", "type": "css"})

    stable_classes = [c for c in attrs.get("class", []) if isinstance(c, str) and len(c) > 2 and not c.startswith("css-") and not c.startswith("sc-")]
    if stable_classes:
        candidates.append({"strategy": "class", "selector": f"{tag}.{stable_classes[0]}", "type": "css"})
        if len(stable_classes) > 1:
            candidates.append({"strategy": "class", "selector": f".{stable_classes[0]}.{stable_classes[1]}", "type": "css"})

    text = element.text
    if text and tag in ("button", "a", "label", "span", "h1", "h2", "h3", "h4"):
        text_clean = _sanitize(text)[:40]
        if text_clean:
            candidates.append({"strategy": "text", "selector": f"{tag}:has-text('{text_clean}')", "type": "css"})

    return candidates
