import os
from dataclasses import dataclass


@dataclass
class HarnessConfig:
    gemini_api_key: str | None = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    gemini_model: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    sandbox_base_url: str = os.environ.get("SANDBOX_BASE_URL", "http://localhost:8080")
    target_url: str = os.environ.get("TARGET_URL", "https://testradius.dev")
    use_sandbox: bool = os.environ.get("USE_SANDBOX", "1") == "1"


config = HarnessConfig()
