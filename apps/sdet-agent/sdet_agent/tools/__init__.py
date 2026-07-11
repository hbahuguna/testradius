"""Tool layer: registry + page / session / file tools.

Registers every tool with the central ToolRegistry. Core tools (page,
session) are callable directly; file tools are also flagged external so the
MCP server can expose them as the "USB-C" interface for external clients.
"""

from __future__ import annotations

from .registry import ToolRegistry, ToolSpec
from . import page_tools, session_tools, file_tools


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()

    reg.register(
        "page_fetch",
        page_tools.page_fetch,
        "Fetch a web page's HTML by URL.",
        {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    )
    reg.register(
        "dom_analyze",
        page_tools.dom_analyze,
        "Extract interactive elements from a URL with accessible-locator hints.",
        {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    )
    reg.register(
        "session_init",
        session_tools.session_init,
        "Start a new SDET session; returns a session_id.",
        {"type": "object", "properties": {"url": {"type": "string"}, "session_id": {"type": "string"}}},
    )
    reg.register(
        "session_record_action",
        session_tools.session_record_action,
        "Record a user action (click/type/select) with its selector.",
        {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "action_type": {"type": "string"},
                "selector": {"type": "string"},
                "value": {"type": "string"},
                "url": {"type": "string"},
            },
            "required": ["session_id", "action_type", "selector"],
        },
    )
    reg.register(
        "session_context",
        session_tools.session_context,
        "Get full context (actions, elements, test code) for a session.",
        {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"]},
    )
    reg.register(
        "file_read",
        file_tools.file_read,
        "Read a file from disk.",
        {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        external=True,
    )
    reg.register(
        "file_save",
        file_tools.file_save,
        "Write content to a file (creates parent dirs).",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
        external=True,
    )
    return reg


__all__ = ["build_registry", "ToolRegistry", "ToolSpec"]
