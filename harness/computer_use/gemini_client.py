"""Gemini computer-use action client (spike).

Uses google-genai with screenshot bytes + step contract JSON to propose a single
desktop action. Harness validates proposals before executing (see spike.py).
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict, Optional


ACTION_TYPES = ("navigate", "click", "double_click", "right_click", "move", "type", "keypress", "scroll", "wait", "assert", "screenshot", "stop")


def _extract_json(text: str) -> Dict[str, Any]:
    s = (text or "").strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {"raw": s}
    except Exception:
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end > start:
            try:
                obj = json.loads(s[start:end + 1])
                return obj if isinstance(obj, dict) else {"raw": s}
            except Exception:
                pass
    return {"raw": s}


class ProposedAction:
    def __init__(self, data: Dict[str, Any]):
        self.data = data or {}
        self.action_type = str(self.data.get("action_type") or self.data.get("action") or "wait").lower()
        self.x = self.data.get("x")
        self.y = self.data.get("y")
        self.text = self.data.get("text") or self.data.get("input") or ""
        self.url = self.data.get("url") or self.data.get("input_url") or ""
        self.key = self.data.get("key") or self.data.get("keys") or ""
        self.scroll_delta = self.data.get("scroll_delta", -300)
        self.wait_seconds = self.data.get("wait_seconds", 1)
        self.reason = str(self.data.get("reason") or self.data.get("thought") or "")

    def to_dict(self) -> Dict[str, Any]:
        return {"action_type": self.action_type, "x": self.x, "y": self.y, "text": self.text, "url": self.url, "key": self.key, "reason": self.reason}


class GeminiComputerUseClient:
    """Live Gemini client (google-genai). Requires GEMINI_API_KEY + SDK."""

    name = "gemini-computer-use"

    def __init__(self, *, model: Optional[str] = None, api_key: Optional[str] = None):
        self.model = model or os.environ.get("GEMINI_COMPUTER_USE_MODEL") or os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    def propose_action(self, *, screenshot_png: bytes, step_contract: Dict[str, Any], history: list[Dict[str, Any]] | None = None) -> ProposedAction:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY/GOOGLE_API_KEY not set")
        try:
            from google import genai  # type: ignore
        except Exception as e:
            raise RuntimeError("google-genai is required for live Gemini computer-use") from e
        system = (
            "You are a desktop GUI agent. Given a screenshot and a compiled test-plan step contract, "
            "output ONLY JSON for ONE action. Prefer visible labels/regions over coordinates; use pixel "
            "coordinates only when needed and within 1440x900. Include 'reason'. "
            "Actions: navigate | click | double_click | right_click | move | type | keypress | scroll | wait | assert | screenshot | stop. "
            "Fields: action_type, x, y, text, url, key, scroll_delta, wait_seconds, reason. "
            "Respect allowed domains and evidence requirements. Never output secrets."
        )
        user = json.dumps({"step_contract": step_contract, "recent_history": (history or [])[-6:]}, ensure_ascii=False, indent=2)
        b64 = base64.b64encode(screenshot_png).decode()
        client = genai.Client(api_key=self.api_key)
        # google-genai multimodal contents: text + image part.
        try:
            from google.genai import types  # type: ignore

            contents = [user, types.Part.from_bytes(data=screenshot_png, mime_type="image/png")]
        except Exception:
            contents = [user, {"inline_data": {"mime_type": "image/png", "data": b64}}]
        # Attach system instruction where supported; fall back to prompt prefix.
        prompt = f"SYSTEM:\n{system}\n\nUSER:\n{user}"
        try:
            from google.genai import types  # type: ignore

            resp = client.models.generate_content(model=self.model, contents=contents, config=types.GenerateContentConfig(system_instruction=system, temperature=0.0))
        except Exception:
            resp = client.models.generate_content(model=self.model, contents=prompt if isinstance(contents, list) else contents)
        text = getattr(resp, "text", None) or str(resp)
        return ProposedAction(_extract_json(text))


class MockGeminiComputerUseClient:
    """Deterministic mock of Gemini proposals for spike tests/demos."""

    name = "mock-gemini-computer-use"

    def __init__(self, *, script: list[Dict[str, Any]] | None = None):
        self.model = "mock-gemini"
        self.script = list(script or [
            {"action_type": "navigate", "url": "https://testradius.dev/", "reason": "Open homepage"},
            {"action_type": "assert", "reason": "Hero visible and page loaded"},
        ])
        self.calls: list[Dict[str, Any]] = []

    def propose_action(self, *, screenshot_png: bytes, step_contract: Dict[str, Any], history: list[Dict[str, Any]] | None = None) -> ProposedAction:
        self.calls.append({"step_id": step_contract.get("step_id"), "history_len": len(history or []), "screenshot_len": len(screenshot_png)})
        if self.script:
            return ProposedAction(self.script.pop(0))
        return ProposedAction({"action_type": "stop", "reason": "mock done"})
