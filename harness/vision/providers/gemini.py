"""Gemini vision provider (STORY-E2B-004.2)."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .base import BaseVisionProvider


def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {"summary": "", "findings": []}
    # Strip markdown fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except Exception:
        # Best-effort: find first JSON object
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                pass
    return {"summary": text[:500], "findings": [], "_parse_error": True}


class GeminiVisionProvider(BaseVisionProvider):
    name = "gemini"

    def __init__(self, api_key: Optional[str] = None, default_model: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.default_model = default_model or os.environ.get("GEMINI_VISION_MODEL") or os.environ.get("GEMINI_MODEL") or "gemini-2.0-flash"

    def analyze_image(
        self,
        image_path: str,
        prompt: str,
        *,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[Dict[str, Any], Optional[str], Optional[str]]:
        if not self.api_key:
            return {"summary": "", "findings": []}, None, "GEMINI_API_KEY/GOOGLE_API_KEY not set"
        try:
            image_bytes = Path(image_path).read_bytes()
        except Exception as e:
            return {"summary": "", "findings": []}, None, f"Failed to read image: {e}"

        model_name = model or self.default_model
        mime = "image/png"
        suffix = Path(image_path).suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            mime = "image/jpeg"
        elif suffix == ".webp":
            mime = "image/webp"

        # Try new google.genai SDK first (matches harness/llm/gemini.py), then legacy google.generativeai
        try:
            from google import genai  # type: ignore

            client = genai.Client(api_key=self.api_key)
            try:
                from google.genai import types  # type: ignore

                contents = [prompt, types.Part.from_bytes(data=image_bytes, mime_type=mime)]
            except Exception:
                contents = [prompt, {"inline_data": {"mime_type": mime, "data": base64.b64encode(image_bytes).decode()}}]
            resp = client.models.generate_content(model=model_name, contents=contents)
            text = getattr(resp, "text", None) or str(resp)
            return _extract_json(text), text, None
        except Exception:
            pass

        try:
            import google.generativeai as genai  # type: ignore

            genai.configure(api_key=self.api_key)
            gm = genai.GenerativeModel(model_name)
            image_part = {"mime_type": mime, "data": image_bytes}
            resp = gm.generate_content([prompt, image_part])
            text = getattr(resp, "text", None) or str(resp)
            return _extract_json(text), text, None
        except Exception as e:
            return {"summary": "", "findings": []}, None, f"Gemini vision analysis failed: {e}"
