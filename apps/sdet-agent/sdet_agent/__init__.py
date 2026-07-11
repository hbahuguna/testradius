"""Standalone SDET Agent — AI-agent-pattern-based Playwright test generator.

Implements the five functional layers from the agent textbook:
  Layer 1: Persona       -> system prompts per graph node
  Layer 2: Tools & Actions -> tools/ registry (direct + MCP)
  Layer 3: Reasoning     -> reasoning/ node executors + Qwen SLM
  Layer 4: Knowledge     -> knowledge/ page-object store + scratchpad memory
  Layer 5: Evaluation    -> guardrails/ deterministic + LLM validators

Plus the agent loop (Sense-Plan-Act-Learn) and tracing observability.
"""

from .core.agent import Agent, AgentResult
from .core.state import AgentState, NodeResult
from .core.scratchpad import Scratchpad
from .core.tracer import Tracer, trace

__version__ = "0.1.0"

__all__ = [
    "Agent",
    "AgentResult",
    "AgentState",
    "NodeResult",
    "Scratchpad",
    "Tracer",
    "trace",
]
