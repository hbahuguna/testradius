from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from testsquad_workbench.sdet_procedure.graph import (
    build_sdet_graph,
    ProcedureGraph,
    Node,
    Edge,
)


class NodeId(Enum):
    N0 = "N0"
    N1 = "N1"
    N2 = "N2"
    N3 = "N3"
    N4 = "N4"
    N5 = "N5"
    N6 = "N6"
    N7 = "N7"
    N8 = "N8"
    N9 = "N9"
    N10 = "N10"
    N11 = "N11"
    N12 = "N12"
    N13 = "N13"
    N14 = "N14"
    N15 = "N15"
    T_SUCCESS = "T_SUCCESS"
    T_ABANDON = "T_ABANDON"
    T_ESCALATE = "T_ESCALATE"


_MAX_CLARIFY = 2
_MAX_REVISE = 2
_MAX_TOTAL_TURNS = 35
_TRANSITIONAL_NODES = {"N2", "N5", "N7"}


AGENT_GREETINGS = {
    "N0": "Hi! I'm your SDET agent. I'll help you create Playwright tests for your web application.\n\nWhat feature or user flow would you like to test today? Describe the scenario you have in mind.",
    "N2": "Let me analyze what you've described. I'll identify the key elements and map out the test requirements.",
    "N3": "I want to make sure I understand correctly. Could you clarify the expected behavior? For example:",
    "N5": "Thanks! Let me determine the intent of this test scenario.",
    "N6": "I see. Let me classify this test to choose the right approach.",
    "N7": "Great, I have a clear picture now. Let me identify the user journey involved.",
    "N8": "Based on what you've described, I'll identify the feature category to apply the right test patterns.",
    "N9": "Now I need to know which page elements to interact with.\n\nPlease interact with the page in the preview panel to the left. Click on each element you want to include in the test (buttons, inputs, links, etc.). I'll capture their selectors automatically.\n\nWhen you've selected all the elements, click \"I'm done selecting elements\" below or type a message to continue.",
    "N10": "I've identified the elements. Let me determine the best locator strategies for each one.",
    "N11": "Let me plan the action sequence step by step.",
    "N12": "Now I'll design the assertions to verify each behavior at every checkpoint.",
    "N13": "Let me apply reliability hardening patterns to make this test robust against flakiness.",
    "N14": "I'm ready to generate the complete Playwright test code now.",
    "N15": "Here's the generated test. Does this look good, or would you like me to make any changes?",
}


CLARIFY_TEMPLATES = {
    "requirement_clear": "To help me better, could you describe:\n\n1. What specific user action starts this flow?\n2. What should happen on success?\n3. Are there any error cases to consider?",
    "needs_clarification": "Let me break this down. Could you tell me:\n\n1. The page or screen where this starts\n2. The main action the user takes\n3. What result you expect",
}

FEATURE_CHIPS = [
    {"id": "auth", "label": "Authentication / Login"},
    {"id": "form", "label": "Form Submission"},
    {"id": "crud", "label": "CRUD Operations"},
    {"id": "navigation", "label": "Navigation Flow"},
    {"id": "data_display", "label": "Data Display"},
    {"id": "search", "label": "Search / Filter"},
    {"id": "payment", "label": "Payment Flow"},
    {"id": "notification", "label": "Notifications"},
    {"id": "media", "label": "Media / Uploads"},
]

TEST_TYPE_CHIPS = [
    {"id": "positive", "label": "Positive (happy path)"},
    {"id": "negative", "label": "Negative (invalid input)"},
    {"id": "edge", "label": "Edge Case"},
    {"id": "error_handling", "label": "Error Handling"},
    {"id": "permission", "label": "Permissions / Access"},
]

REVIEW_CHIPS = [
    {"id": "approve", "label": "Looks good, accept"},
    {"id": "revise", "label": "Needs changes"},
    {"id": "abandon", "label": "Cancel / start over"},
]

N9_ELEMENT_CHIPS = [
    {"id": "done_selecting", "label": "I'm done selecting elements"},
]

COMPLEXITY_CHIPS = [
    {"id": "simple", "label": "Simple (happy path only)"},
    {"id": "moderate", "label": "Moderate (with error states)"},
    {"id": "complex", "label": "Complex (multi-step)"},
]


FALLBACK_AGENT = """I understand you want to test the {feature} feature with a {test_type} test.

Here's the Playwright test for this scenario:

```typescript
import {{ test, expect }} from '@playwright/test';

test.describe('{feature_display} - {test_type_display}', () => {{
  test('should {description}', async ({{ page }}) => {{
    await page.goto('{url}');
    // TODO: Implement test steps based on selected elements
    // Elements: {element_summary}
  }});
}});
```

Would you like me to refine this test or add more details?"""


@dataclass
class RecordedAction:
    css_path: str
    tag: str
    action_type: str  # click | fill | select | check | hover | navigate
    value: str = ""
    text: str = ""
    step_order: int = 0
    element_id: str = ""
    label: str = ""
    locator: str = ""  # Suggested Playwright locator
    accessible_name: str = ""


ACTION_TYPE_KEYWORDS: Dict[str, List[str]] = {
    "click": ["button", "a", "span", "div", "li", "label", "h1", "h2", "h3", "img"],
    "fill": ["input", "textarea"],
    "select": ["select"],
    "check": ["checkbox"],
    "navigate": [""],
}

_TEMPLATED_RESPONSES: Dict[str, str] = {
    "N7": "Great, I have a clear picture now. Let me identify the user journey involved.\n\nBased on what you described, this flow involves:\n{journey_steps}\n\nDoes this look correct?",
    "N10": "I've analyzed the selected elements. Here are the recommended locator strategies:\n\n{locator_summary}\n\nEach uses Playwright's accessible locator API for reliability.",
    "N11": "Let me plan the action sequence based on what you've recorded:\n\n{action_sequence}\n\nHere's what I'll generate:\n{action_plan}",
    "N12": "For each action, I'll add assertions to verify the result:\n\n{assertion_plan}\n\nThis ensures every step is validated.",
    "N14": "I'm generating the complete Playwright test now using:\n\n- {action_count} recorded user actions\n- {element_count} targeted elements\n- Locator strategies optimized for reliability\n\nOne moment please...",
}


def infer_action_type(tag: str, element_type: Optional[str] = None) -> str:
    tag_lower = tag.lower()
    if element_type == "checkbox" or tag_lower == "input" and element_type == "checkbox":
        return "check"
    if tag_lower == "select":
        return "select"
    if tag_lower in ("input", "textarea"):
        return "fill"
    if tag_lower in ("a", "button"):
        return "click"
    return "click"


def compute_playwright_locator(el: Dict[str, Any]) -> str:
    tag = el.get("tag", "").lower()
    accessible_name = el.get("accessible_name", "")
    label = accessible_name or el.get("label", "") or el.get("text", "") or ""
    el_id = el.get("id_attr", "") or el.get("id", "")
    aria_label = el.get("aria_label", "")
    placeholder = el.get("placeholder", "")
    role = el.get("role", "")
    name = el.get("name", "")

    if aria_label:
        return f"page.getByRole('{_infer_role(tag, role)}', {{ name: '{_escape(aria_label)}' }})"
    if accessible_name and len(accessible_name) < 80:
        return f"page.getByLabel('{_escape(accessible_name)}')"
    if label and len(label) < 80:
        return f"page.getByLabel('{_escape(label)}')"
    if placeholder:
        return f"page.getByPlaceholder('{_escape(placeholder)}')"
    if role:
        return f"page.getByRole('{role}', {{ name: /{_escape(label[:30])}/i }})"
    if el_id:
        return f"page.locator('#{el_id}')"
    if label:
        return f"page.getByText('{_escape(label[:40])}')"
    if name:
        return f"page.locator('[{name}=\"{_escape(name)}\"]')"
    return f"page.locator('{el.get('css_path', tag)}')"


def _infer_role(tag: str, role: str) -> str:
    if role:
        return role
    mapping = {"a": "link", "button": "button", "input": "textbox", "textarea": "textbox",
               "select": "combobox", "checkbox": "checkbox", "radio": "radio"}
    return mapping.get(tag.lower(), "button")


def _escape(s: str) -> str:
    return s.replace("'", "\\'").replace("\n", " ").strip()


TEST_TYPE_KEYWORDS: Dict[str, List[str]] = {
    "positive": ["success", "happy", "valid", "correct", "should work", "positive"],
    "negative": ["invalid", "wrong", "bad", "incorrect", "fail", "negative", "error input"],
    "edge": ["boundary", "edge", "limit", "empty", "maximum", "minimum", "special"],
    "error_handling": ["error", "exception", "crash", "timeout", "network", "server error", "500"],
    "permission": ["permission", "access", "unauthorized", "forbidden", "role", "admin", "restrict"],
}

FEATURE_TYPE_KEYWORDS: Dict[str, List[str]] = {
    "auth": ["login", "logout", "sign in", "sign up", "register", "password", "authentication", "sso", "oauth"],
    "form": ["form", "submit", "input", "field", "fill", "enter data"],
    "crud": ["create", "read", "update", "delete", "crud", "add new", "edit", "remove"],
    "navigation": ["navigation", "navigate", "menu", "link", "route", "page transition", "redirect"],
    "data_display": ["display", "list", "table", "grid", "show", "view data", "render"],
    "search": ["search", "filter", "find", "query", "lookup", "autocomplete"],
    "payment": ["payment", "checkout", "cart", "purchase", "pay", "transaction", "billing"],
    "notification": ["notification", "alert", "toast", "message", "push", "notify"],
    "media": ["upload", "download", "image", "file", "video", "attachment", "media"],
}


def _word_match(text: str, keyword: str) -> bool:
    return re.search(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE) is not None


def _any_word_match(text: str, keywords: List[str]) -> bool:
    return any(_word_match(text, kw) for kw in keywords)


def classify_test_type(text: str) -> str:
    text_lower = text.lower()
    for test_type, keywords in TEST_TYPE_KEYWORDS.items():
        if _any_word_match(text_lower, keywords):
            return test_type
    return "positive"


def classify_feature_type(text: str) -> str:
    text_lower = text.lower()
    for feat_type, keywords in FEATURE_TYPE_KEYWORDS.items():
        if _any_word_match(text_lower, keywords):
            return feat_type
    return "form"


def classify_clarify_intent(text: str) -> str:
    text_lower = text.lower()
    clarify_words = ["what do you mean", "clarify", "not sure", "confused", "i don't understand", "unsure", "repeat"]
    clear_words = ["yes", "yeah", "sure", "correct", "right", "exactly", "let me explain", "i mean", "got it"]

    if any(w in text_lower for w in clarify_words):
        return "needs_clarification"
    if any(w in text_lower for w in clear_words):
        return "requirement_clear"
    if len(text.split()) < 3:
        return "needs_clarification"
    if text_lower.startswith("test") or "should" in text_lower:
        return "requirement_clear"
    return "requirement_clear"


def classify_review_intent(text: str) -> str:
    text_lower = text.lower()
    approve_words = ["looks good", "yes", "accept", "approve", "great", "perfect", "fine", "good", "works"]
    revise_words = ["change", "revise", "modify", "update", "add", "edit", "fix", "different", "instead", "also", "need"]
    abandon_words = ["cancel", "stop", "abandon", "never mind", "forget", "start over", "quit", "exit"]

    if any(w in text_lower for w in abandon_words):
        return "abandon"
    if any(w in text_lower for w in revise_words):
        return "revise"
    if any(w in text_lower for w in approve_words):
        return "accept"
    return "accept"


@dataclass
class Turn:
    node_id: str
    role: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StateSnapshot:
    current_node: str
    total_turns: int
    clarify_count: int
    revise_count: int
    feature_type: Optional[str]
    test_type: Optional[str]
    is_complete: bool


class ConversationState:
    def __init__(self, url: str = "", elements: Optional[List[Dict]] = None):
        self.graph = build_sdet_graph()
        self.url = url
        self.elements = elements or []
        self.selected_elements: List[Dict] = []
        self.recorded_actions: List[RecordedAction] = []
        self.current_node_id: str = "N0"
        self.history: List[Turn] = []
        self.hub_decisions: Dict[str, str] = {}
        self.clarify_count: int = 0
        self.revise_count: int = 0
        self.total_turns: int = 0
        self.feature_type: Optional[str] = None
        self.test_type: Optional[str] = None
        self.scenario_description: str = ""
        self.jira_context: str = ""
        self.metadata: Dict[str, Any] = {}

    def snapshot(self) -> StateSnapshot:
        return StateSnapshot(
            current_node=self.current_node_id,
            total_turns=self.total_turns,
            clarify_count=self.clarify_count,
            revise_count=self.revise_count,
            feature_type=self.feature_type,
            test_type=self.test_type,
            is_complete=self.current_node_id in ("T_SUCCESS", "T_ABANDON", "T_ESCALATE"),
        )

    def get_successors(self) -> List[Edge]:
        return self.graph.successors(self.current_node_id)

    def get_node(self) -> Optional[Node]:
        return self.graph.get_node(self.current_node_id)

    def is_terminal(self) -> bool:
        return self.graph.is_terminal(self.current_node_id)

    def is_hub(self) -> bool:
        n = self.graph.get_node(self.current_node_id)
        return n is not None and n.is_decision_hub

    def add_turn(self, role: str, content: str, metadata: Optional[Dict] = None) -> Turn:
        turn = Turn(
            node_id=self.current_node_id,
            role=role,
            content=content,
            metadata=metadata or {},
        )
        self.history.append(turn)
        self.total_turns += 1
        return turn

    def transition_to(self, target_node_id: str, decision: Optional[str] = None) -> bool:
        successors = self.get_successors()
        target_ids = {e.target_id for e in successors}

        if target_node_id not in target_ids and not self.is_terminal():
            return False

        if decision and self.is_hub():
            self.hub_decisions[self.current_node_id] = decision

        self.current_node_id = target_node_id

        if target_node_id == "T_SUCCESS":
            pass
        elif target_node_id == "T_ABANDON":
            pass
        elif target_node_id == "T_ESCALATE":
            pass
        elif target_node_id == "N3":
            self.clarify_count += 1
        elif target_node_id == "N7" and self.revise_count > 0:
            self.revise_count += 1
        elif target_node_id == "N15":
            if self.hub_decisions.get("N15") == "revise":
                self.revise_count += 1

        return True

    def _advance_past_user_node(self) -> None:
        from testsquad_workbench.sdet_procedure.graph import NodeRole
        while True:
            node = self.graph.get_node(self.current_node_id)
            if node is None or node.role != NodeRole.USER:
                break
            successors = self.graph.successors(self.current_node_id)
            if not successors:
                break
            self.current_node_id = successors[0].target_id

    def _advance_past_transitional_nodes(self) -> None:
        while self.current_node_id in _TRANSITIONAL_NODES:
            successors = self.graph.successors(self.current_node_id)
            if not successors:
                break
            self.current_node_id = successors[0].target_id

    def classify_and_route(self, text: str) -> Optional[str]:
        if self.total_turns >= _MAX_TOTAL_TURNS:
            return "T_ESCALATE"

        node = self.get_node()
        if node is None:
            return None

        if not node.is_decision_hub:
            successors = self.get_successors()
            if successors:
                return successors[0].target_id
            return None

        hub_id = self.current_node_id

        if hub_id == "N3":
            intent = classify_clarify_intent(text)
            if intent == "needs_clarification":
                if self.clarify_count >= _MAX_CLARIFY:
                    return "N5"
                return "N4"
            return "N5"

        elif hub_id == "N6":
            self.test_type = classify_test_type(text)
            return "N7"

        elif hub_id == "N8":
            self.feature_type = classify_feature_type(text)
            return "N9"

        elif hub_id == "N15":
            intent = classify_review_intent(text)
            if intent == "revise":
                if self.revise_count >= _MAX_REVISE:
                    return "T_SUCCESS"
                return "N7"
            elif intent == "abandon":
                return "T_ABANDON"
            return "T_SUCCESS"

        return None

    def _build_journey_steps(self) -> str:
        feature = self.feature_type or "the feature"
        test_type = self.test_type or ""
        lines = [
            f"- **Given**: User is on the {feature} page",
            f"- **When**: User performs the {test_type} test scenario" if test_type else "- **When**: User performs the test scenario",
            f"- **Then**: System responds appropriately",
        ]
        if self.scenario_description:
            lines.insert(1, f"- **Scenario**: {self.scenario_description[:100]}")
        return "\n".join(lines)

    def _build_locator_summary(self) -> str:
        if not self.selected_elements:
            return "No elements selected yet."
        lines = []
        for i, el in enumerate(self.selected_elements, 1):
            tag = el.get("tag", "?")
            text = (el.get("text", "") or el.get("label", "") or "")[:40]
            locator = compute_playwright_locator(el)
            lines.append(f"{i}. **{tag}** - {text or '(no text)'}\n   `{locator}`")
        return "\n".join(lines) if lines else "No elements selected."

    def _build_action_sequence(self) -> str:
        if not self.recorded_actions:
            return "No actions recorded yet."
        lines = []
        for a in self.recorded_actions:
            target = a.label or a.text[:40] or a.tag
            lines.append(f"  {a.step_order}. **{a.action_type}** on _{target}_ → `{a.locator}`")
        return "\n".join(lines)

    def _build_action_plan(self) -> str:
        if not self.recorded_actions:
            return "1. Navigate to the page\n2. Interact with the elements\n3. Verify the results"
        lines = []
        for a in self.recorded_actions:
            target = a.label or a.text[:40] or a.tag
            lines.append(f"{a.step_order}. `{a.locator}` → {a.action_type} this element")
        return "\n".join(lines)

    def _build_assertion_plan(self) -> str:
        if not self.recorded_actions:
            return "- Assert page loads successfully\n- Assert expected content is visible"
        has_nav = any(a.action_type in ("click", "navigate") for a in self.recorded_actions)
        has_fill = any(a.action_type == "fill" for a in self.recorded_actions)
        has_check = any(a.action_type == "check" for a in self.recorded_actions)
        lines = []
        if has_nav:
            lines.append("- After navigation/click: assert URL or heading is correct")
            lines.append("- After navigation/click: assert expected elements are visible")
        if has_fill:
            lines.append("- After fill: assert input value is set correctly")
            lines.append("- After form action: assert success message or state change")
        if has_check:
            lines.append("- After check/toggle: assert checkbox/radio state changed")
        lines.append("- Final: assert the expected outcome is displayed")
        return "\n".join(lines)

    def get_agent_response(self) -> str:
        nid = self.current_node_id
        tag = f"[{nid}] "

        if nid in _TEMPLATED_RESPONSES:
            template = _TEMPLATED_RESPONSES[nid]
            if nid == "N7":
                return tag + template.format(journey_steps=self._build_journey_steps())
            elif nid == "N10":
                return tag + template.format(locator_summary=self._build_locator_summary())
            elif nid == "N11":
                return tag + template.format(
                    action_sequence=self._build_action_sequence(),
                    action_plan=self._build_action_plan(),
                )
            elif nid == "N12":
                return tag + template.format(assertion_plan=self._build_assertion_plan())
            elif nid == "N14":
                return tag + template.format(
                    action_count=len(self.recorded_actions),
                    element_count=len(self.selected_elements),
                )

        if nid in AGENT_GREETINGS:
            return tag + AGENT_GREETINGS[nid]

        if nid == "N3":
            intent = self.hub_decisions.get("N3", "requirement_clear")
            return tag + CLARIFY_TEMPLATES.get(intent, AGENT_GREETINGS["N3"])

        return tag + "Let me process that and generate the test for you."

    def get_suggestion_chips(self) -> List[Dict]:
        nid = self.current_node_id

        if nid in ("N6",):
            return TEST_TYPE_CHIPS
        elif nid == "N8":
            return FEATURE_CHIPS
        elif nid == "N15":
            return REVIEW_CHIPS
        elif nid == "N9":
            return N9_ELEMENT_CHIPS
        elif nid == "N3":
            return [
                {"id": "clarify_more", "label": "Let me explain more"},
                {"id": "proceed", "label": "That's correct, proceed"},
            ]
        else:
            return []

    def can_handle_user_input(self) -> bool:
        if self.is_terminal():
            return False
        node = self.get_node()
        if node is None:
            return False
        return True

    def record_action(self, action: RecordedAction) -> None:
        step_order = len(self.recorded_actions) + 1
        action.step_order = step_order
        self.recorded_actions.append(action)

    def record_actions_batch(self, actions: List[Dict]) -> None:
        for a in actions:
            accessible_name = a.get("accessible_name", "")
            recorded = RecordedAction(
                css_path=a.get("css_path", a.get("cssPath", "")),
                tag=a.get("tag", ""),
                action_type=a.get("action_type", infer_action_type(a.get("tag", ""), a.get("type"))),
                value=a.get("value", ""),
                text=a.get("text", ""),
                step_order=a.get("step_order", len(self.recorded_actions) + 1),
                element_id=a.get("id", a.get("element_id", "")),
                label=accessible_name or a.get("label", a.get("aria_label", "")),
                locator=a.get("locator", ""),
                accessible_name=accessible_name,
            )
            if not recorded.locator:
                recorded.locator = compute_playwright_locator({**a, "accessible_name": accessible_name})
            # Deduplicate actions based on css_path and action_type
            if any(
                existing.css_path == recorded.css_path and existing.action_type == recorded.action_type
                for existing in self.recorded_actions
            ):
                continue
            self.recorded_actions.append(recorded)

    def get_action_summary(self) -> str:
        if not self.recorded_actions:
            return "No actions recorded yet."
        lines = []
        for a in self.recorded_actions:
            parts = [f"  {a.step_order}. {a.action_type} {a.tag}"]
            if a.label or a.text:
                parts.append(f"  ({a.label or a.text[:40]})")
            parts.append(f"  → {a.locator}")
            lines.append(" ".join(parts))
        return "\n".join(lines)

    def process_user_input(self, text: str, selected_elements: Optional[List[Dict]] = None, recorded_actions: Optional[List[Dict]] = None) -> Dict[str, Any]:
        if selected_elements is not None:
            for el in selected_elements:
                if not any(e.get("css_path") == el.get("cssPath", el.get("css_path")) for e in self.selected_elements):
                    self.selected_elements.append(el)

        if recorded_actions is not None:
            self.record_actions_batch(recorded_actions)

        self.add_turn("user", text)

        # Capture Jira ticket context separately so downstream test generation
        # can prioritize it over recorded actions (it must not be treated as a
        # generic chat message). The TicketIntegration panel emits a block that
        # starts with the "Jira Ticket Context:" marker.
        if "Jira Ticket Context:" in text:
            self.jira_context = text
            desc_match = re.search(
                r"--- Description ---\s*(.*?)(?:-{40,}|\Z)", text, re.DOTALL
            )
            self.scenario_description = (
                desc_match.group(1).strip() if desc_match else text.strip()
            )
        elif not self.scenario_description and len(text.strip()) > 3:
            self.scenario_description = text.strip()

        next_node = self.classify_and_route(text)
        if next_node is None:
            return {
                "message": {"role": "assistant", "content": "I'm not sure how to proceed. Could you rephrase that?"},
                "next_node": self.current_node_id,
                "suggestion_chips": [],
                "is_complete": False,
            }

        if not self.transition_to(next_node):
            return {
                "message": {"role": "assistant", "content": "I encountered an unexpected state. Let me reset and try again."},
                "next_node": "N5",
                "suggestion_chips": TEST_TYPE_CHIPS,
                "is_complete": False,
            }

        self._advance_past_user_node()
        self._advance_past_transitional_nodes()

        is_complete = self.is_terminal()

        if not is_complete:
            agent_content = self.get_agent_response()
            self.add_turn("assistant", agent_content)
        else:
            terminal_messages = {
                "T_SUCCESS": "Test generation complete! The test has been saved. You can start a new session to create another test.",
                "T_ABANDON": "Session ended. Feel free to start a new session when you're ready.",
                "T_ESCALATE": "This conversation has exceeded the maximum length. Please start a new session.",
            }
            agent_content = terminal_messages.get(self.current_node_id, "Session complete.")
            self.add_turn("assistant", agent_content)

        return {
            "message": {"role": "assistant", "content": agent_content},
            "next_node": self.current_node_id,
            "suggestion_chips": self.get_suggestion_chips() if not is_complete else [],
            "is_complete": is_complete,
        }

    def generate_test_code(self) -> str:
        feature_type = self.feature_type or "unknown"
        test_type = self.test_type or "positive"

        feature_display = feature_type.replace("_", " ").title()
        test_type_display = test_type.replace("_", " ").title()

        desc = self.scenario_description or "perform the user flow"
        test_name = desc.lower().replace(" ", "_")[:40]

        action_steps = []
        if not self.recorded_actions:
            action_steps.append("    // TODO: Add test steps")
        else:
            for a in self.recorded_actions:
                loc = a.locator or compute_playwright_locator({"tag": a.tag, "label": a.label, "text": a.text, "css_path": a.css_path})
                if a.action_type == "click":
                    action_steps.append(f"    await {loc}.click();")
                elif a.action_type == "fill":
                    action_steps.append(f"    await {loc}.fill('{_escape(a.value or 'test-value')}');")
                elif a.action_type == "select":
                    action_steps.append(f"    await {loc}.selectOption('{_escape(a.value or 'option')}');")
                elif a.action_type == "check":
                    action_steps.append(f"    await {loc}.check();")
                elif a.action_type == "hover":
                    action_steps.append(f"    await {loc}.hover();")

        assertions = []
        if self.recorded_actions:
            last = self.recorded_actions[-1]
            target = last.label or last.text[:40] or last.tag
            if last.action_type in ("click", "navigate"):
                assertions.append(f"    await expect(page).toHaveURL(/.*/);")
            assertions.append(f"    await expect(page.getByText('{_escape(target[:30])}')).toBeVisible();")
        else:
            assertions.append("    // TODO: Add assertions")

        test_code = f"""import {{ test, expect }} from '@playwright/test';

test.describe('{feature_display} - {test_type_display}', () => {{
  test('{desc[:60]}', async ({{ page }}) => {{
    await page.goto('{self.url}');
    await expect(page).toHaveTitle(/./);

{chr(10).join(action_steps)}

{chr(10).join(assertions)}
  }});
}});
"""
        return test_code

    def reset_to_node(self, target_node_id: str) -> bool:
        if target_node_id not in [t.node_id for t in self.history]:
            return False
        if target_node_id == self.current_node_id:
            return True
        truncate_idx = None
        for i, turn in enumerate(self.history):
            if turn.node_id == target_node_id:
                truncate_idx = i
                break
        if truncate_idx is None:
            return False
        self.history = self.history[:truncate_idx]
        self.current_node_id = target_node_id
        self.clarify_count = sum(1 for t in self.history if t.node_id == "N3")
        self.revise_count = max(0, sum(1 for t in self.history if t.node_id == "N15") - 1)
        self.hub_decisions = {
            nid: dec for nid, dec in self.hub_decisions.items()
            if int(nid[1:]) < int(target_node_id[1:])
        } if target_node_id[1:].isdigit() else {}
        self.selected_elements = []
        return True

    def inject_welcome(self):
        msg = "[N0] " + AGENT_GREETINGS["N0"]
        self.add_turn("assistant", msg)
