"""E2B API client."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional


class E2BError(Exception):
    pass


class E2BClient:
    def __init__(self, api_key: Optional[str] = None, api_url: Optional[str] = None):
        self.api_key = api_key or os.environ.get("E2B_API_KEY")
        self.api_url = api_url or os.environ.get("E2B_API_URL") or "https://api.e2b.dev"
        if not self.api_key:
            raise E2BError("E2B_API_KEY required")

    def health_check(self) -> bool:
        return True
