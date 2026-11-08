"""Action schema + primitive mapping for computer-use runner (008.5.1)."""
from __future__ import annotations

from typing import Any, Dict

SUPPORTED_ACTIONS = (
    "screenshot", "click", "double_click", "right_click", "move",
    "type", "keypress", "scroll", "wait", "navigate", "assert", "stop",
)

# JSON-schema-style description for function/tool calling (Gemini function calling).
# The live client sends this as the single allowed function; mock ignores but records.
ACTION_FUNCTION_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "name": "desktop_action",
    "description": "Execute one desktop GUI action in the sandbox.",
    "parameters": {
        "type": "object",
        "properties": {
            "action_type": {"type": "string", "enum": list(SUPPORTED_ACTIONS)},
            "x": {"type": "integer", "description": "Pixel X in [0,1440)"},
            "y": {"type": "integer", "description": "Pixel Y in [0,900)"},
            "text": {"type": "string", "description": "Text to type"},
            "url": {"type": "string", "description": "URL to navigate (allowed domains only)"},
            "key": {"type": "string", "description": "Key to press, e.g. Return"},
            "scroll_delta": {"type": "integer"},
            "wait_seconds": {"type": "number"},
            "reason": {"type": "string"},
        },
        "required": ["action_type"],
    },
}


# Model/provider aliases -> canonical action_type (models often emit primitive names).
_ACTION_ALIASES = {
    "press_key": "keypress",
    "key_combination": "keypress",
    "scroll_document": "scroll",
    "scroll_at": "scroll",
    "click_at": "click",
    "hover_at": "move",
    "type_text_at": "type",
    "type_text": "type",
    "go_back": "keypress",
    "go_forward": "keypress",
}


class ProposedAction:
    """Normalized desktop action proposed by Gemini (validated before execution)."""

    def __init__(self, data: Dict[str, Any] | None = None):
        self.data = dict(data or {})
        raw = str(self.data.get("action_type") or self.data.get("action") or "wait").lower()
        self.action_type = _ACTION_ALIASES.get(raw, raw)
        self.x = self.data.get("x")
        self.y = self.data.get("y")
        self.text = self.data.get("text") or self.data.get("input") or ""
        self.url = self.data.get("url") or self.data.get("input_url") or ""
        _key = self.data.get("key") or self.data.get("keys") or ""
        # CU key_combination may pass a list of key names; join as xdotool chord (e.g. ["Page_Down"]).
        if isinstance(_key, (list, tuple)):
            parts = [str(k) for k in _key]
        else:
            parts = [str(_key)] if _key else []
        # xdotool key names: "PageDown"/"Page_Down" are silently ignored; correct names are Next/Prior.
        _KEY_ALIASES = {"page_down": "Next", "pagedown": "Next", "page_up": "Prior", "pageup": "Prior"}
        self.key = "+".join(_KEY_ALIASES.get(p.lower(), p) for p in parts)
        self.scroll_delta = self.data.get("scroll_delta", -300)
        self.wait_seconds = self.data.get("wait_seconds", 1)
        self.reason = str(self.data.get("reason") or self.data.get("thought") or "")

    def to_dict(self) -> Dict[str, Any]:
        return {"action_type": self.action_type, "x": self.x, "y": self.y, "text": self.text, "url": self.url, "key": self.key, "reason": self.reason}

    def __repr__(self) -> str:  # pragma: no cover
        return f"ProposedAction({self.action_type!r})"


def execute_action(action: ProposedAction, primitives: Any) -> bool:
    """Map a validated action onto E2B desktop primitives."""
    at = action.action_type
    p = primitives
    if at == "screenshot":
        try:
            p.screenshot()
            return True
        except Exception:
            return False
    if at == "navigate" and action.url:
        return bool(p.navigate(action.url))
    if at in {"click", "double_click", "right_click"} and action.x is not None and action.y is not None:
        return bool(p.click(int(action.x), int(action.y), button={"right_click": "right"}.get(at, "left"), double=(at == "double_click")))
    if at == "move" and action.x is not None and action.y is not None:
        return bool(p.move_mouse(int(action.x), int(action.y)))
    if at == "type" and action.text:
        return bool(p.type_text(str(action.text)))
    if at == "keypress" and action.key:
        return bool(p.press_key(str(action.key)))
    if at == "scroll":
        return bool(p.scroll(delta_y=int(action.scroll_delta or -300)))
    if at == "wait":
        return bool(p.wait(float(action.wait_seconds or 0)))
    if at in {"assert", "stop"}:
        # No-op primitive; assertion is judged by observe/assess in runner.
        return True
    return False
