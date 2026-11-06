"""MCP/manual context intake adapters (STORY-E2B-008.1).

Control-plane only: fetch/receive source payloads, normalize to ContextBundle.
No secrets persisted. MCP adapters accept payloads/resources (mockable) and
fall back to manual when unavailable.
"""

from .adapters import (
    BaseContextAdapter,
    DocsContextAdapter,
    FigmaContextAdapter,
    GitHubContextAdapter,
    JiraContextAdapter,
    ManualContextAdapter,
)
from .intake import ContextIntake, ContextSourceConfig, MCPServerConfig

__all__ = [
    "BaseContextAdapter",
    "ContextIntake",
    "ContextSourceConfig",
    "DocsContextAdapter",
    "FigmaContextAdapter",
    "GitHubContextAdapter",
    "JiraContextAdapter",
    "MCPServerConfig",
    "ManualContextAdapter",
]
