"""Reasoning layer: rule-based node handlers for the SDET procedure graph.

This module provides deterministic, zero-cost execution of every graph node
so the agent runs end-to-end today. In Phase 2 the generative nodes (N2, N5,
N9, N11, N14) are upgraded to call the Qwen SLM; the routing hubs (N3, N6,
N8, N15) stay rule-based because they are deterministic classification
decisions (textbook Ch.4: "back guardrails with hard-coded fallback").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..core.state import AgentState, NodeResult

# Explicit labels injected by the workbench (api.py) take precedence over
# keyword scanning, so a recorded action like "select role" cannot flip the
# intent away from the UI's chosen test type.
_EXPLICIT_FEATURE = re.compile(r"^\s*feature:\s*([a-z_]+)", re.I | re.M)
_EXPLICIT_INTENT = re.compile(r"^\s*test type:\s*([a-z_]+)", re.I | re.M)

# Feature keyword -> feature type used by N8 (FeatureHub)
FEATURE_KEYWORDS: dict[str, list[str]] = {
    "auth": ["login", "sign in", "signin", "log in", "password", "authenticate", "credential"],
    "form": ["form", "submit", "input", "field", "application", "profile", "settings", "register"],
    "crud": ["create", "update", "delete", "admin", "user list", "manage"],
    "navigation": ["navigate", "nav", "menu", "sidebar", "link", "route"],
    "data_display": ["table", "list", "display", "dashboard", "chart", "show"],
    "search": ["search", "query", "filter", "find"],
    "payment": ["payment", "pay", "checkout", "card", "invoice", "billing"],
    "notification": ["notification", "alert", "email", "message", "notify"],
    "media": ["upload", "image", "video", "file", "download"],
}

# Intent keywords -> test type used by N5 (DetermineIntent)
INTENT_KEYWORDS: dict[str, list[str]] = {
    "positive": ["happy", "success", "valid", "correct", "positive", "working"],
    "negative": ["invalid", "error", "fail", "wrong", "reject", "negative"],
    "edge": ["boundary", "edge", "limit", "max", "min", "exceed"],
    "error_handling": ["timeout", "crash", "exception", "server error", "500"],
    "permission": ["permission", "unauthorized", "forbidden", "role", "access", "admin only"],
}


@dataclass
class Classification:
    label: str
    reasoning: str


def classify_feature(scenario: str) -> Classification:
    m = _EXPLICIT_FEATURE.search(scenario)
    if m:
        val = m.group(1).strip().lower()
        if val in FEATURE_KEYWORDS:
            return Classification(val, f"Used explicit Feature label '{val}' from scenario.")
    text = scenario.lower()
    scores: dict[str, int] = {}
    for ftype, kws in FEATURE_KEYWORDS.items():
        scores[ftype] = sum(1 for kw in kws if kw in text)
    best = max(scores, key=scores.get) if any(scores.values()) else "form"
    return Classification(best, f"Matched keywords for '{best}' feature type.")


def classify_intent(scenario: str) -> Classification:
    m = _EXPLICIT_INTENT.search(scenario)
    if m:
        val = m.group(1).strip().lower()
        if val in INTENT_KEYWORDS:
            return Classification(val, f"Used explicit Test Type label '{val}' from scenario.")
    text = scenario.lower()
    scores: dict[str, int] = {}
    for itype, kws in INTENT_KEYWORDS.items():
        scores[itype] = sum(1 for kw in kws if kw in text)
    if not any(scores.values()):
        return Classification("positive", "No negative/edge signals; assuming happy-path positive test.")
    best = max(scores, key=scores.get)
    return Classification(best, f"Detected '{best}' signals in the scenario text.")


def needs_clarification(scenario: str) -> bool:
    """Heuristic: require clarification if scenario is extremely vague."""
    text = scenario.strip().lower()
    if len(text) < 10:
        return True
    # Missing both a verb-action and a subject -> unclear
    has_action = any(w in text for w in ["test", "submit", "click", "fill", "login", "navigate", "search"])
    has_target = any(w in text for w in ["form", "page", "button", "application", "login", "search"])
    return not (has_action and has_target)


def generate_code_template(state: AgentState) -> str:
    """Produce a valid Playwright skeleton from accumulated context (Phase 1)."""
    url = state.url or "http://localhost:3000"
    feature = state.get("feature_type", "form") or "form"
    intent = state.get("intent", "positive") or "positive"
    # Clean, deterministic describe name derived from the classified feature/intent
    # (never from the raw scenario text, which can be very long).
    describe = f"{feature.title()}{intent.title()}Test"
    scenario_label = state.get("scenario_description") or f"{intent} scenario for the {feature} page"

    return f"""import {{ test, expect }} from "@playwright/test";

test.describe("{describe}", () => {{
  test.beforeEach(async ({{ page }}) => {{
    await page.goto("{url}");
  }});

  test("{scenario_label}", async ({{ page }}) => {{
    await expect(page).toHaveURL("{url}");
    // TODO: fill locators, actions, and assertions from N9-N13 context
  }});
}});
"""
