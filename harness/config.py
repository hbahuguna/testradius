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


# Cloud Room configuration
CLOUDROOM_URL = os.environ.get("CLOUDROOM_URL", "http://127.0.0.1:9840")
CLOUDROOM_TOKEN = os.environ.get("CLOUDROOM_TOKEN") or os.environ.get("CLOUDROOM_API_TOKEN")
CLOUDROOM_PROJECT = os.environ.get("CLOUDROOM_PROJECT")
EXECUTOR_TYPE = os.environ.get("EXECUTOR_TYPE") or os.environ.get("EXECUTOR", "local")


@dataclass
class ExecutorSettings:
    """Executor configuration settings."""

    executor_type: str = EXECUTOR_TYPE
    cloudroom_url: str = CLOUDROOM_URL
    cloudroom_token: str | None = CLOUDROOM_TOKEN
    cloudroom_project: str | None = CLOUDROOM_PROJECT
    timeout_seconds: int = int(os.environ.get("EXECUTOR_TIMEOUT", "600"))


executor_settings = ExecutorSettings()


def validate_executor_config() -> Dict[str, Any]:
    """Validate executor configuration."""
    errors = []
    warnings = []
    if EXECUTOR_TYPE.lower() == "cloudroom":
        if not CLOUDROOM_TOKEN:
            errors.append("CLOUDROOM_TOKEN required when EXECUTOR_TYPE=cloudroom")
        if not CLOUDROOM_URL:
            errors.append("CLOUDROOM_URL required when EXECUTOR_TYPE=cloudroom")
    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}
