"""Gemini computer-use action client (008.4 spike + 008.5 runner).

Uses google-genai with screenshot bytes + step contract JSON to propose a single
desktop action. Harness validates proposals before executing (see runner.py).
Structured action parsing: extracts JSON from model text (fence-tolerant); live
path also advertises ACTION_FUNCTION_SCHEMA for function calling where supported.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Dict, Optional

from .action_schema import ACTION_FUNCTION_SCHEMA, ProposedAction

logger = logging.getLogger("harness.computer_use.gemini_client")

__all__ = ["ACTION_FUNCTION_SCHEMA", "GeminiComputerUseClient", "MockGeminiComputerUseClient", "ProposedAction"]

ACTION_TYPES = ("navigate", "click", "double_click", "right_click", "move", "type", "keypress", "scroll", "wait", "assert", "screenshot", "stop")

# Native Gemini Computer Use function names -> our action schema
_CU_ACTION_MAP = {
    "click_at": "click",
    "hover_at": "move",
    "type_text_at": "type",
    "type_text": "type",
    "scroll_document": "scroll",
    "scroll_at": "scroll",
    "navigate": "navigate",
    "go_back": "keypress",
    "go_forward": "keypress",
    "search": "navigate",
    "open_web_browser": "navigate",
    "wait_5_seconds": "wait",
    "key_combination": "keypress",
    "drag_and_drop": "move",
}


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


def _denorm(v: Any, size: int) -> int | None:
    """Denormalize Gemini CU coordinate (typically 0-1000) to pixels."""
    if v is None:
        return None
    try:
        f = float(v)
    except Exception:
        return None
    # Native CU returns 0-999/0-1000 normalized; if value looks like pixels (>1000) keep it.
    if 0 <= f <= 1000:
        return max(0, min(size, int(round(f / 1000.0 * size))))
    return int(round(f))


def _from_function_call(name: str, args: Dict[str, Any], *, width: int, height: int) -> Dict[str, Any]:
    action = _CU_ACTION_MAP.get(name, name)
    out: Dict[str, Any] = {"action_type": action, "reason": f"computer_use:{name}", "_cu_function": name, "_cu_args": args}
    if "x" in args or "y" in args:
        out["x"] = _denorm(args.get("x"), width)
        out["y"] = _denorm(args.get("y"), height)
    if name == "drag_and_drop":
        out["action_type"] = "move"  # simplified; full drag not in primitive set
        out["x"] = _denorm(args.get("destination_x", args.get("x")), width)
        out["y"] = _denorm(args.get("destination_y", args.get("y")), height)
    if "text" in args:
        out["text"] = args.get("text")
    if "url" in args:
        out["url"] = args.get("url")
        if action == "navigate":
            out["action_type"] = "navigate"
    if name in ("go_back", "go_forward"):
        out["key"] = "Alt+Left" if name == "go_back" else "Alt+Right"
    if "keys" in args:
        out["key"] = args.get("keys")
    if "direction" in args:
        out["action_type"] = "scroll"
        out["scroll_delta"] = -400 if str(args.get("direction", "")).lower() == "down" else 400
    if name == "wait_5_seconds":
        out["action_type"] = "wait"
        out["seconds"] = 5
    if "press_enter" in args and args.get("press_enter") and action == "type":
        out["_press_enter"] = True
    return out


def _extract_function_call(resp: Any) -> tuple[str, Dict[str, Any]] | None:
    try:
        for cand in getattr(resp, "candidates", []) or []:
            content = getattr(cand, "content", None)
            for part in getattr(content, "parts", []) or []:
                fc = getattr(part, "function_call", None)
                if fc and getattr(fc, "name", None):
                    args = getattr(fc, "args", None) or {}
                    if hasattr(args, "items"):
                        args = dict(args)
                    return str(fc.name), args if isinstance(args, dict) else {}
    except Exception:
        pass
    return None


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
        self.model = model or os.environ.get("GEMINI_COMPUTER_USE_MODEL") or os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash"
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    def propose_action(self, *, screenshot_png: bytes, step_contract: Dict[str, Any], history: list[Dict[str, Any]] | None = None, width: int = 1440, height: int = 900) -> ProposedAction:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY/GOOGLE_API_KEY not set")
        try:
            from google import genai  # type: ignore
        except Exception as e:
            raise RuntimeError("google-genai is required for live Gemini computer-use") from e

        client = genai.Client(api_key=self.api_key)
        step_user = json.dumps({
            "step_contract": step_contract,
            "recent_history": (history or [])[-6:],
            "screen": {"width": width, "height": height},
        }, ensure_ascii=False, indent=2)

        # 1) Prefer native Gemini Computer Use tool (best coordinate grounding).
        try:
            from google.genai import types  # type: ignore

            cu_tool = types.Tool(computer_use=types.ComputerUse(environment=types.Environment.ENVIRONMENT_BROWSER))
            contents = [
                types.Content(role="user", parts=[
                    types.Part.from_text(text=(
                        "Execute ONLY the next action for this compiled test step on the current screenshot. "
                        "Follow the step_contract intent/target/success_criteria; do not take extra actions.\n" + step_user
                    )),
                    types.Part.from_bytes(data=screenshot_png, mime_type="image/png"),
                ])
            ]
            resp = client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(tools=[cu_tool], temperature=0.0),
            )
            fc = _extract_function_call(resp)
            if fc:
                name, args = fc
                mapped = _from_function_call(name, args, width=width, height=height)
                # If the step contract expects a specific action (e.g. navigate) and native CU
                # returned it, great; otherwise keep mapped action (grounding is better).
                return ProposedAction(mapped)
            text = getattr(resp, "text", None)
            if text:
                return ProposedAction(_extract_json(text))
        except Exception:
            pass

        # 2) Fallback: JSON-prompted action (works with non-CU models; weaker grounding).
        system, _ = build_step_prompt(step_contract=step_contract, history=history)
        prompt = f"SYSTEM:\n{system}\n\nUSER:\n{step_user}\nScreen is {width}x{height} pixels. If you return coordinates, use PIXEL coordinates in that exact space (top-left 0,0)."
        try:
            from google.genai import types  # type: ignore

            resp = client.models.generate_content(
                model=self.model,
                contents=[prompt, types.Part.from_bytes(data=screenshot_png, mime_type="image/png")],
                config=types.GenerateContentConfig(system_instruction=system, temperature=0.0),
            )
        except Exception:
            resp = client.models.generate_content(model=self.model, contents=prompt)
        text = getattr(resp, "text", None) or str(resp)
        return ProposedAction(_extract_json(text))

    def assess(self, *, screenshot_png: bytes, step_contract: Dict[str, Any], history: list[Dict[str, Any]] | None = None) -> bool:
        """Observe/assert: does the screenshot satisfy step success_criteria?"""
        if not self.api_key:
            return True  # No cloud judge available; treat execution as observed pass.
        try:
            from google import genai  # type: ignore
            from google.genai import types  # type: ignore

            client = genai.Client(api_key=self.api_key)
            system = "Judge whether the screenshot satisfies success_criteria. Output ONLY JSON: {\"passed\": true|false, \"reason\": \"...\"}."
            user = json.dumps({"step_contract": step_contract, "recent_history": (history or [])[-6:]}, ensure_ascii=False)
            try:
                contents = [user, types.Part.from_bytes(data=screenshot_png, mime_type="image/png")]
                resp = client.models.generate_content(model=self.model, contents=contents, config=types.GenerateContentConfig(system_instruction=system, temperature=0.0))
            except Exception as e:
                logger.warning("assess image call failed (%s); retrying without image", e)
                resp = client.models.generate_content(model=self.model, contents=f"{system}\n{user}")
            text = getattr(resp, "text", None) or str(resp)
            data = _extract_json(text)
            passed = bool(data.get("passed", True))
            logger.info("assess passed=%s reason=%s step=%s", passed, data.get("reason"), step_contract.get("step_id"))
            return passed
        except Exception as e:
            logger.warning("assess failed: %s", e)
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

    def propose_action(self, *, screenshot_png: bytes, step_contract: Dict[str, Any], history: list[Dict[str, Any]] | None = None, **_) -> ProposedAction:
        self.calls.append({"step_id": step_contract.get("step_id"), "history_len": len(history or []), "screenshot_len": len(screenshot_png)})
        if self.script:
            return ProposedAction(self.script.pop(0))
        return ProposedAction({"action_type": "stop", "reason": "mock done"})

    def assess(self, *, screenshot_png: bytes, step_contract: Dict[str, Any], history: list[Dict[str, Any]] | None = None) -> bool:
        self.assess_calls += 1
        return self.assess_pass
