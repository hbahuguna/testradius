"""Base interface for vision model providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple


class BaseVisionProvider(ABC):
    name: str = "base"

    @abstractmethod
    def analyze_image(
        self,
        image_path: str,
        prompt: str,
        *,
        model: Optional[str] = None,
        **kwargs: Any,
    ) -> Tuple[Dict[str, Any], Optional[str], Optional[str]]:
        """Analyze an image.

        Returns: (parsed_payload, raw_text, error)
        parsed_payload should contain at least {"summary": str, "findings": list[dict]}.
        """
        raise NotImplementedError
