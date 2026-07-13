"""Core page-analysis tools (direct calls, not external).

page_fetch downloads rendered HTML; dom_analyze extracts interactive
elements with suggested accessible-selector hints. These are the "core"
tools called directly by the agent during the IdentifyElements /
DetermineLocators steps.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("sdet_agent.tools.page")


def page_fetch(url: str, timeout: int = 30) -> str:
    """Fetch a page's HTML and return it as a string."""
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError as e:
        return f"[page_fetch error: {e}]"


_INTERACTIVE_TAGS = {"a", "button", "input", "select", "textarea", "form"}
_ROLE_HINTS = {
    "a": "link",
    "button": "button",
    "input": "textbox",
    "select": "combobox",
    "textarea": "textbox",
}


def dom_analyze(url: str) -> list[dict[str, Any]]:
    """Extract interactive elements with accessible-name suggestions."""
    html = page_fetch(url)
    if html.startswith("[page_fetch error"):
        return [{"error": html}]
    soup = BeautifulSoup(html, "html.parser")
    elements: list[dict[str, Any]] = []
    for tag in soup.find_all(_INTERACTIVE_TAGS):
        tag_name = tag.name
        attrs = dict(tag.attrs) if tag.attrs else {}
        aria = {k: attrs.pop(k) for k in list(attrs.keys()) if k.startswith("aria-")}
        text = (tag.get_text(strip=True) or "").strip()
        from testsquad_workbench.generation.html_parser import _compute_accessible_name
        name_attr = _compute_accessible_name(tag, attrs, aria, text) or text
        role_hint = _ROLE_HINTS.get(tag_name, tag_name)
        # Build an accessible locator suggestion
        if name_attr:
            locator = f"getByRole('{role_hint}', {{ name: /{name_attr[:40]}/i }})"
        elif tag.get("id"):
            locator = f"locator('#{tag.get('id')}')"
        else:
            locator = f"locator('{tag_name}')"
        elements.append(
            {
                "tag": tag_name,
                "name": name_attr,
                "role_hint": role_hint,
                "suggested_locator": locator,
                "attributes": {
                    k: v
                    for k, v in tag.attrs.items()
                    if k in ("id", "type", "href", "placeholder", "aria-label", "name", "class")
                },
            }
        )
    return elements[:100]
