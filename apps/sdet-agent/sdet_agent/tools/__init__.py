"""Tool layer: registry + page / session / file tools.

Registers every tool with the central ToolRegistry. Core tools (page,
session) are callable directly; file tools are also flagged external so the
MCP server can expose them as the "USB-C" interface for external clients.
"""

from __future__ import annotations

from .registry import ToolRegistry, ToolSpec
from . import page_tools, session_tools, file_tools, knowledge_tools, browser_tools


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

    reg.register(
        "knowledge_list_page_objects",
        knowledge_tools.knowledge_list_page_objects,
        "List all discovered Playwright Page Objects (classes, locators, methods).",
        {},
    )
    reg.register(
        "knowledge_list_repo_patterns",
        knowledge_tools.knowledge_list_repo_patterns,
        "List common test patterns and utility functions found in the repo.",
        {},
    )

    # ---- Agentic browser tools (live UI exploration) ----
    # MCP (in-process) is primary; the "cli" backend is a subprocess fallback.
    reg.register(
        "browser_start",
        browser_tools.browser_start,
        "Start a live browser session for agentic exploration (backend=mcp|cli).",
        {
            "type": "object",
            "properties": {
                "headless": {"type": "boolean"},
                "backend": {"type": "string", "enum": ["mcp", "cli"]},
            },
        },
    )
    reg.register(
        "browser_stop",
        browser_tools.browser_stop,
        "Close the live browser session.",
        {},
    )
    reg.register(
        "browser_navigate",
        browser_tools.browser_navigate,
        "Navigate the live browser to a URL.",
        {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    )
    reg.register(
        "browser_click",
        browser_tools.browser_click,
        "Click an element by accessible locator (role|name, label, text, placeholder, css, or auto).",
        {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "kind": {"type": "string", "enum": ["auto", "role", "label", "text", "placeholder", "css"]},
            },
            "required": ["target"],
        },
    )
    reg.register(
        "browser_type",
        browser_tools.browser_type,
        "Fill an input by accessible locator with text.",
        {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "text": {"type": "string"},
                "kind": {"type": "string", "enum": ["auto", "role", "label", "text", "placeholder", "css"]},
            },
            "required": ["target", "text"],
        },
    )
    reg.register(
        "browser_select",
        browser_tools.browser_select,
        "Select an option in a <select> by accessible locator.",
        {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "value": {"type": "string"},
                "kind": {"type": "string", "enum": ["auto", "role", "label", "text", "placeholder", "css"]},
            },
            "required": ["target", "value"],
        },
    )
    reg.register(
        "browser_wait_for",
        browser_tools.browser_wait_for,
        "Wait for an element to become visible.",
        {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "kind": {"type": "string", "enum": ["auto", "role", "label", "text", "placeholder", "css"]},
                "timeout": {"type": "integer"},
            },
            "required": ["target"],
        },
    )
    reg.register(
        "browser_assert_visible",
        browser_tools.browser_assert_visible,
        "Assert an element is visible (returns ok=false if not).",
        {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "kind": {"type": "string", "enum": ["auto", "role", "label", "text", "placeholder", "css"]},
            },
            "required": ["target"],
        },
    )
    reg.register(
        "browser_assert_text",
        browser_tools.browser_assert_text,
        "Assert expected text appears (optionally scoped to a locator).",
        {
            "type": "object",
            "properties": {
                "expected": {"type": "string"},
                "target": {"type": "string"},
                "kind": {"type": "string", "enum": ["auto", "role", "label", "text", "placeholder", "css"]},
            },
            "required": ["expected"],
        },
    )
    reg.register(
        "browser_assert_url",
        browser_tools.browser_assert_url,
        "Assert the current URL matches a regex pattern.",
        {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]},
    )
    reg.register(
        "browser_get_url",
        browser_tools.browser_get_url,
        "Get the current browser URL.",
        {},
    )
    reg.register(
        "browser_snapshot",
        browser_tools.browser_snapshot,
        "Capture the accessibility tree + interactive elements of the current page.",
        {},
    )

    return reg


__all__ = ["build_registry", "ToolRegistry", "ToolSpec"]
