"""MCP-compatible tool gateway and a deterministic in-memory client (E2-S3)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

from .types import ToolResult


class MCPError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class MCPDenied(MCPError):
    pass


@dataclass(frozen=True)
class MCPTool:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})


class MCPClient(Protocol):
    async def list_tools(self) -> list[MCPTool]: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult: ...


class FakeMCPClient:
    """Test/demo client. Handlers make the fixture behavior explicit."""

    def __init__(
        self,
        tools: list[MCPTool] | None = None,
        *,
        responses: dict[str, ToolResult] | None = None,
        a11y_violations: list[dict[str, Any]] | None = None,
    ):
        self.tools = tools or default_tools()
        self.responses = responses or {}
        self.a11y_violations = a11y_violations or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[MCPTool]:
        return list(self.tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append((name, arguments))
        if name in self.responses:
            return self.responses[name]
        if name == "browser.check_a11y":
            return ToolResult(
                ok=True,
                output={"violations": self.a11y_violations},
            )
        if name == "browser.accessibility_tree":
            return ToolResult(ok=True, output={"tree": {"role": "WebArea", "children": []}})
        if name == "browser.navigate":
            return ToolResult(ok=True, output={"url": arguments.get("url", "")})
        if name == "browser.assert_text":
            return ToolResult(ok=True, output={"text": arguments.get("text", "")})
        if name == "browser.screenshot":
            return ToolResult(
                ok=True,
                output={"path": arguments.get("path", "screenshot.png")},
                evidence=[str(arguments.get("path", "screenshot.png"))],
            )
        return ToolResult(ok=True, output={})


class ToolRegistry:
    """Allowlist first, citation check second, network/tool call last."""

    def __init__(
        self,
        client: MCPClient,
        *,
        allowed_by_role: dict[str, list[str]] | None = None,
        timeout_seconds: float = 15.0,
    ):
        self._client = client
        self._allowed = {
            role: set(tools) for role, tools in (allowed_by_role or default_allowlist()).items()
        }
        self._timeout = timeout_seconds
        self.calls: list[dict[str, Any]] = []
        self.denials: list[dict[str, Any]] = []

    async def list_tools(self, role: str) -> list[MCPTool]:
        allowed = self._allowed.get(role, set())
        return [tool for tool in await self._client.list_tools() if tool.name in allowed]

    def allows(self, role: str, tool: str) -> bool:
        return tool in self._allowed.get(role, set())

    async def call(
        self,
        role: str,
        tool: str,
        arguments: dict[str, Any],
        citations: list[str],
    ) -> ToolResult:
        if not self.allows(role, tool):
            self._deny(role, tool, "tool_not_allowed")
        if not citations:
            self._deny(role, tool, "citation_required")
        try:
            result = await asyncio.wait_for(
                self._client.call_tool(tool, arguments), timeout=self._timeout
            )
        except TimeoutError as exc:
            raise MCPError("tool_timeout", f"tool timed out: {tool}") from exc
        except MCPError:
            raise
        except Exception as exc:
            raise MCPError("tool_failed", f"tool failed: {tool}") from exc
        self.calls.append(
            {
                "role": role,
                "tool": tool,
                "arguments": arguments,
                "citations": list(citations),
                "ok": result.ok,
            }
        )
        return result

    def _deny(self, role: str, tool: str, reason: str) -> None:
        self.denials.append({"role": role, "tool": tool, "reason": reason})
        raise MCPDenied(reason, f"{tool} denied for {role}: {reason}")


def default_tools() -> list[MCPTool]:
    return [
        MCPTool("browser.navigate", "Open a URL", {"type": "object"}),
        MCPTool("browser.click", "Click an element by role/name or test id", {"type": "object"}),
        MCPTool("browser.type", "Type into an element", {"type": "object"}),
        MCPTool("browser.assert_text", "Assert visible text", {"type": "object"}),
        MCPTool("browser.check_a11y", "Inspect accessible names", {"type": "object"}),
        MCPTool(
            "browser.accessibility_tree",
            "Read the accessibility tree",
            {"type": "object"},
        ),
        MCPTool("browser.screenshot", "Capture a screenshot", {"type": "object"}),
    ]


def default_allowlist() -> dict[str, list[str]]:
    return {
        "executor": [
            "browser.navigate",
            "browser.click",
            "browser.type",
            "browser.assert_text",
            "browser.check_a11y",
            "browser.accessibility_tree",
            "browser.screenshot",
        ]
    }
