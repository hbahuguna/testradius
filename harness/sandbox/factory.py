"""Sandbox provider factory."""
from __future__ import annotations

import os

from .base import BaseSandboxProvider


def create_sandbox_provider(provider_type: str | None = None) -> BaseSandboxProvider:
    provider_type = provider_type or os.environ.get("SANDBOX_PROVIDER") or os.environ.get("EXECUTOR_TYPE") or "local"
    provider_type = provider_type.lower()
    
    if provider_type == "e2b":
        from .e2b_provider import E2BSandboxProvider
        return E2BSandboxProvider()
    elif provider_type == "local":
        from .local_provider import LocalSandboxProvider
        return LocalSandboxProvider()
    else:
        raise ValueError(f"Unknown sandbox provider: {provider_type}")
