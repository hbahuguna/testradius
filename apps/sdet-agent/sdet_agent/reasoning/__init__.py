"""Reasoning layer: node executors, rule-based classifiers, and Qwen wiring."""

from .node_executor import NodeExecutor
from .rule_reasoner import classify_feature, classify_intent, needs_clarification
from .templates import NODE_SYSTEM_PROMPTS
from .llm_factory import LLMFactory, LLMClientConfig
from .qwen_client import QwenClient
from .hy3_client import Hy3Client
from .llm_reasoner import LLMReasoner, build_llm_handlers, extract_code

__all__ = [
    "NodeExecutor",
    "classify_feature",
    "classify_intent",
    "needs_clarification",
    "NODE_SYSTEM_PROMPTS",
    "LLMFactory",
    "LLMClientConfig",
    "QwenClient",
    "Hy3Client",
    "LLMReasoner",
    "build_llm_handlers",
    "extract_code",
]
