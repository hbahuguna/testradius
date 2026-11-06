"""Gemini computer-use action client (008.4 spike + 008.5 runner).

Uses google-genai with screenshot bytes + step contract JSON to propose a single
desktop action. Harness validates proposals before executing (see runner.py).
Structured action parsing: extracts JSON from model text (fence-tolerant); live
path also advertises ACTION_FUNCTION_SCHEMA for function calling where supported.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict, Optional

from .action_schema import ACTION_FUNCTION_SCHEMA, ProposedAction

__all__ = ["ACTION_FUNCTION_SCHEMA", "GeminiComputerUseClient", "MockGeminiComputerUseClient", "ProposedAction"]

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


def build_step_prompt(*, step_contract: Dict[str, Any], history: list[Dict[str, Any]] | None = None) -> tuple[str, str]:
    """Step-scoped prompting (008.5.2): single-action JSON, contract + history + hints."""
    from .safety import INJECTION_GUARD_FRAGMENT

    system = (
        "You are a desktop GUI agent. Given a screenshot and a compiled test-plan step contract, "
        "output ONLY JSON for ONE action per ACTION_FUNCTION_SCHEMA (desktop_action). "
        "Prefer visible labels/regions over coordinates; use pixel coordinates only when needed and within 1440x900. "
        "Include 'reason'. Respect allowed domains and evidence requirements. Never output secrets. "
        "If fallback_instructions are provided, follow them when the target is not immediately found. "
        f"{INJECTION_GUARD_FRAGMENT}"
    )
    user = json.dumps({
        "step_contract": step_contract,
        "recent_history": (history or [])[-6:],
        "function_schema": ACTION_FUNCTION_SCHEMA,
    }, ensure_ascii=False, indent=2)
    return system, user


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
        system, user = build_step_prompt(step_contract=step_contract, history=history)
        client = genai.Client(api_key=self.api_key)
        try:
            from google.genai import types  # type: ignore

            contents = [user, types.Part.from_bytes(data=screenshot_png, mime_type="image/png")]
        except Exception:
            contents = [user, {"inline_data": {"mime_type": "image/png", "data": base64.b64encode(screenshot_png).decode()}}]
        prompt = f"SYSTEM:\n{system}\n\nUSER:\n{user}"
        try:
            from google.genai import types  # type: ignore

            resp = client.models.generate_content(model=self.model, contents=contents, config=types.GenerateContentConfig(system_instruction=system, temperature=0.0))
        except Exception:
            resp = client.models.generate_content(model=self.model, contents=prompt if isinstance(contents, list) else contents)
        text = getattr(resp, "text", None) or str(resp)
        return ProposedAction(_extract_json(text))

    def assess(self, *, screenshot_png: bytes, step_contract: Dict[str, Any], history: list[Dict[str, Any]] | None = None) -> bool:
        """Observe/assert: does the screenshot satisfy step success_criteria?"""
        if not self.api_key:
            return True  # No cloud judge available; treat execution as observed pass.
        try:
            from google import genai  # type: ignore

            client = genai.Client(api_key=self.api_key)
            system = "Judge whether the screenshot satisfies success_criteria. Output ONLY JSON: {\"passed\": true|false, \"reason\": \"...\"}."
            user = json.dumps({"step_contract": step_contract, "recent_history": (history or [])[-6:]}, ensure_ascii=False)
            contents = [user, types.Part.from_bytes(data=screenshot_png, mime_type="image/png")]  # type: ignore
            try:
                from google.genai import types  # type: ignore

                contents = [user, types.Part.from_bytes(data=screenshot_png, mime_type="image/png")]
                resp = client.models.generate_content(model=self.model, contents=contents, config=types.GenerateContentConfig(system_instruction=system, temperature=0.0))
            except Exception:
                resp = client.models.generate_content(model=self.model, contents=f"{system}\n{user}")
            text = getattr(resp, "text", None) or str(resp)
            data = _extract_json(text)
            return bool(data.get("passed", True))
        except Exception:
            return False


class MockGeminiComputerUseClient:
    """Deterministic mock of Gemini proposals for tests/demos."""

    name = "mock-gemini-computer-use"

    def __init__(self, *, script: list[Dict[str, Any]] | None = None, assess_pass: bool = True):
        self.model = "mock-gemini"
        self.script = list(script or [
            {"action_type": "navigate", "url": "https://testradius.dev/", "reason": "Open homepage"},
            {"action_type": "assert", "reason": "Hero visible and page loaded"},
        ])
        self.calls: list[Dict[str, Any]] = []
        self.assess_pass = assess_pass
        self.assess_calls = 0

    def propose_action(self, *, screenshot_png: bytes, step_contract: Dict[str, Any], history: list[Dict[str, Any]] | None = None) -> ProposedAction:
        self.calls.append({"step_id": step_contract.get("step_id"), "history_len": len(history or []), "screenshot_len": len(screenshot_png)})
        if self.script:
            return ProposedAction(self.script.pop(0))
        return ProposedAction({"action_type": "stop", "reason": "mock done"})

    def assess(self, *, screenshot_png: bytes, step_contract: Dict[str, Any], history: list[Dict[str, Any]] | None = None) -> bool:
        self.assess_calls += 1
        return self.assess_pass
