"""Locator-strategy guardrail.

Enforces the accessible-locator priority order from the SDET best practices
(textbook Ch.1 Layer 2 + the repo's own page-object conventions):

  getByRole > getByLabel > getByPlaceholder > getByText > getByTestId > CSS

and bans fixed timeouts (waitForTimeout) which cause flakiness.
"""

from __future__ import annotations

import re

# Order matters: earlier entries are preferred. We flag code that leans on
# the lowest-priority strategies when higher-priority ones are available
# elsewhere, or that uses banned patterns outright.
_BANNED_PATTERNS = [
    (r"waitForTimeout\s*\(", "uses fixed timeout waitForTimeout (flaky)"),
    (r"page\.waitForSelector\s*\(", "uses waitForSelector (prefer expect().toBeVisible())"),
]

_PREFERRED = [
    r"getByRole\s*\(",
    r"getByLabel\s*\(",
    r"getByPlaceholder\s*\(",
    r"getByText\s*\(",
    r"getByTestId\s*\(",
]


def check_locators(code: str, context: dict) -> tuple[bool, str]:
    for pattern, msg in _BANNED_PATTERNS:
        if re.search(pattern, code):
            return False, msg

    has_preferred = any(re.search(p, code) for p in _PREFERRED)
    uses_css = bool(re.search(r"\.locator\(\s*['\"]", code)) or bool(
        re.search(r"page\.locator\(\s*['\"]", code)
    )
    if uses_css and not has_preferred:
        return False, "relies only on CSS locators; prefer accessible locators"
    if has_preferred:
        return True, "uses accessible locators, no banned patterns"
    return True, "no locators detected (acceptable for scaffolding)"


def check_assertions(code: str, context: dict) -> tuple[bool, str]:
    """Every action should have a corresponding assertion cluster."""
    actions = len(
        re.findall(r"\.(fill|click|goto|selectOption|check|type|press|submit)\s*\(", code)
    )
    assertions = len(re.findall(r"expect\s*\(", code))
    if actions == 0:
        return True, "no actions to assert"
    if assertions < 1:
        return False, f"{actions} actions but 0 assertions"
    if assertions < actions:
        return False, f"{actions} actions but only {assertions} assertions (coverage gap)"
    return True, f"{assertions} assertions for {actions} actions"
