"""Cloudflare Workers AI provider for free LLM access.

Uses Cloudflare Workers AI REST API to serve DeepSeek Coder and other models.
Free tier: 10,000 requests/day, no credit card required.
Requires: CLOUDFLARE_API_TOKEN (or CLOUDFLARE_AI_TOKEN) + CLOUDFLARE_ACCOUNT_ID env vars.
"""
import os
import json
import logging
from typing import List, Optional
import httpx

from testsquad_shared.models import LLMRequest, LLMResponse, LLMModelInfo
from testsquad_core.intelligence.providers.base import BaseProvider

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "@cf/deepseek-ai/deepseek-coder-6.7b-instruct"

SUPPORTED_MODELS = [
    LLMModelInfo(
        name=DEFAULT_MODEL,
        description="DeepSeek Coder 6.7B - Code generation and analysis",
        context_window=16384,
    ),
    LLMModelInfo(
        name="@cf/qwen/qwen2.5-coder-7b-instruct",
        description="Qwen 2.5 Coder 7B - Code generation",
        context_window=32768,
    ),
    LLMModelInfo(
        name="@cf/meta/llama-3.1-8b-instruct",
        description="Llama 3.1 8B - General purpose",
        context_window=8192,
    ),
    LLMModelInfo(
        name="@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        description="Llama 3.3 70B FP8 - Fast, high quality",
        context_window=131072,
    ),
]


class CloudflareProvider(BaseProvider):
    def __init__(self, api_key: str = None):
        super().__init__(api_key or os.getenv("CLOUDFLARE_API_TOKEN") or os.getenv("CLOUDFLARE_AI_TOKEN") or "")
        self.account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")

    async def list_models(self) -> List[LLMModelInfo]:
        return SUPPORTED_MODELS

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model_name or DEFAULT_MODEL
        url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/run/{model}"

        messages = [{"role": "system", "content": "You are a code analysis assistant."}]
        messages.append({"role": "user", "content": request.prompt})

        payload = {
            "messages": messages,
            "max_tokens": request.max_tokens or 2048,
            "temperature": request.temperature or 0.1,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()

                if not data.get("success"):
                    errors = data.get("errors", [{"message": "Unknown error"}])
                    error_msg = "; ".join(e.get("message", "") for e in errors)
                    return LLMResponse(
                        content=f"Error: Cloudflare API error: {error_msg}",
                        model_name=model,
                        provider_name="Cloudflare",
                    )

                result = data.get("result", {})
                content = result.get("response", "")

                if not isinstance(content, str):
                    content = json.dumps(content)

                return LLMResponse(
                    content=content,
                    model_name=model,
                    provider_name="Cloudflare",
                )

        except httpx.TimeoutException:
            return LLMResponse(
                content="Error: Cloudflare API request timed out after 120s",
                model_name=model,
                provider_name="Cloudflare",
            )
        except httpx.HTTPStatusError as e:
            return LLMResponse(
                content=f"Error: Cloudflare API HTTP {e.response.status_code}: {e.response.text[:500]}",
                model_name=model,
                provider_name="Cloudflare",
            )
        except Exception as e:
            logger.error(f"Cloudflare API call failed: {e}")
            return LLMResponse(
                content=f"Error: {e}",
                model_name=model,
                provider_name="Cloudflare",
            )
