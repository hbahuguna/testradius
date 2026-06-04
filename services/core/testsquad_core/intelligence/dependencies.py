from fastapi import Header, HTTPException, status
from typing import Optional
from testsquad_core.intelligence.registry import llm_registry
from testsquad_core.intelligence.providers.base import BaseProvider

async def get_llm_client(
    x_llm_provider: str = Header(None),
    x_llm_api_key: str = Header(None),
    x_llm_model: str = Header(None)
) -> BaseProvider:
    # Sanitize model name to prevent 400 errors from trailing commas/whitespace
    sanitized_model = x_llm_model.strip().strip(",") if x_llm_model else None
    """
    Dependency to get an LLM client, using headers for dynamic configuration
    if provided, otherwise falling back to standard registry clients.
    """
    provider = x_llm_provider or "Google" # Default
    
    client = llm_registry.get_client(provider, api_key_override=x_llm_api_key)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"LLM Provider {provider} not configured and no API key provided."
        )
    
    return client
