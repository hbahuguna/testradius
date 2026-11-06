"""OpenAI vision provider (optional, STORY-E2B-004.2)."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .base import BaseVisionProvider
from .gemini import _extract_json


class OpenAIVisionProvider(BaseVisionProvider):
    name = "openai"

    def __init__(self, api_key: Optional[str] = None, default_model: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.default_model = default_model or os.environ.get("OPENAI_VISION_MODEL") or "gpt-4o-mini"

    def analyze_image(
        self,
        image_path: str,
        prompt: str,
        *,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[Dict[str, Any], Optional[str], Optional[str]]:
        if not self.api_key:
            return {"summary": "", "findings": []}, None, "OPENAI_API_KEY not set"
        try:
            from openai import OpenAI  # type: ignore
        except Exception as e:
            return {"summary": "", "findings": []}, None, f"openai package not available: {e}"
        try:
            data = base64.b64encode(Path(image_path).read_bytes()).decode()
            mime = "image/jpeg" if Path(image_path).suffix.lower() in {".jpg", ".jpeg"} else "image/png"
            client = OpenAI(api_key=self.api_key)
            resp = client.chat.completions.create(
                model=model or self.default_model,
                messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}]}],
                temperature=0.1,
            )
            text = resp.choices[0].message.content or ""
            return _extract_json(text), text, None
        except Exception as e:
            return {"summary": "", "findings": []}, None, f"OpenAI vision analysis failed: {e}"
