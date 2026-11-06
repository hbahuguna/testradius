"""Anthropic vision provider (optional, STORY-E2B-004.2)."""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .base import BaseVisionProvider
from .gemini import _extract_json


class AnthropicVisionProvider(BaseVisionProvider):
    name = "anthropic"

    def __init__(self, api_key: Optional[str] = None, default_model: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.default_model = default_model or os.environ.get("ANTHROPIC_VISION_MODEL") or "claude-sonnet-4-5-20250929"

    def analyze_image(
        self,
        image_path: str,
        prompt: str,
        *,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[Dict[str, Any], Optional[str], Optional[str]]:
        if not self.api_key:
            return {"summary": "", "findings": []}, None, "ANTHROPIC_API_KEY not set"
        try:
            import anthropic  # type: ignore
        except Exception as e:
            return {"summary": "", "findings": []}, None, f"anthropic package not available: {e}"
        try:
            data = base64.b64encode(Path(image_path).read_bytes()).decode()
            mime = "image/jpeg" if Path(image_path).suffix.lower() in {".jpg", ".jpeg"} else "image/png"
            client = anthropic.Anthropic(api_key=self.api_key)
            resp = client.messages.create(
                model=model or self.default_model,
                max_tokens=1200,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}},
                    {"type": "text", "text": prompt},
                ]}],
            )
            text = "".join(getattr(b, "text", "") for b in getattr(resp, "content", []) or [])
            return _extract_json(text), text, None
        except Exception as e:
            return {"summary": "", "findings": []}, None, f"Anthropic vision analysis failed: {e}"
