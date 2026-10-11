"""LLM-guided conversational layer (A3).

Public surface:
    build_llm(config)          -> LLMCallable | None (None = deterministic mode)
    ConversationFlow           -> orchestrates intake, gates, evaluation
    parse_slots / Slots        -> intake parsing
    evaluate / Evaluation      -> result evaluation
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..config import TiaConfig
from .context import ALLOWED_KEYS, PrivacyError, build_context
from .evaluate import Evaluation, evaluate
from .flow import ConversationFlow, FlowResult, UI
from .intake import LLMCallable, Slots, missing_slots, parse_slots, validate
from .toolbox import Evidence, RadiusToolbox, Toolbox


def build_llm(config: TiaConfig, store=None) -> Optional[LLMCallable]:
    """Return a chat callable bound to the user's provider, or None if unset.

    None means the flow runs in deterministic (template) mode — the agent must
    stay usable without an LLM key.
    """
    from ..llm import LLMError, get_adapter

    try:
        adapter = get_adapter(config, store)
    except LLMError:
        return None

    def call(messages: List[Dict[str, str]]) -> str:
        return adapter.chat(messages).text

    return call


__all__ = [
    "ALLOWED_KEYS",
    "ConversationFlow",
    "Evaluation",
    "Evidence",
    "FlowResult",
    "LLMCallable",
    "PrivacyError",
    "RadiusToolbox",
    "Slots",
    "Toolbox",
    "UI",
    "build_context",
    "build_llm",
    "evaluate",
    "missing_slots",
    "parse_slots",
    "validate",
]