"""Playwright-backed tool client (E2-S4).

This is the cell's MCP tool surface for the browser. It intentionally exposes
only high-level actions; selectors are never synthesized by the model outside
the tool contract. The accessibility check is a blocking signal, not a repair
hint.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .mcp import MCPTool, default_tools
from .types import ToolResult


class PlaywrightMCPClient:
    def __init__(
        self,
        *,
        workspace_dir: str,
        allow_network: bool = False,
        allowed_hosts: list[str] | None = None,
    ):
        self._workspace = Path(workspace_dir)
        self._allow_network = allow_network
        self._allowed_hosts = set(allowed_hosts or [])
        self._playwright = None
        self._browser = None
        self._page = None
        self._closed = False
        self._console: list[dict[str, Any]] = []
        self._network: list[dict[str, Any]] = []

    async def list_tools(self) -> list[MCPTool]:
        return default_tools()

    async def health(self) -> bool:
        return not self._closed

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        try:
            return await self._dispatch(name, arguments)
        finally:
            if name == "browser.close":
                await self.close()

    async def _dispatch(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if self._closed:
            return ToolResult(ok=False, error="browser_closed")
        page = await self._page_or_start()
        if name == "browser.navigate":
            url = str(arguments.get("url", ""))
            try:
                self._check_network(url)
            except ValueError as exc:
                return ToolResult(ok=False, error=str(exc))
            try:
                await page.goto(url, wait_until="domcontentloaded")
            except Exception as exc:
                return ToolResult(ok=False, error=f"navigation_failed:{type(exc).__name__}")
            return ToolResult(ok=True, output={"url": page.url})
        if name == "browser.click":
            try:
                locator = self._locator(page, arguments)
            except ValueError as exc:
                return ToolResult(ok=False, error=str(exc))
            await locator.click()
            return ToolResult(ok=True, output={})
        if name == "browser.type":
            try:
                locator = self._locator(page, arguments)
            except ValueError as exc:
                return ToolResult(ok=False, error=str(exc))
            await locator.fill(str(arguments.get("text", "")))
            return ToolResult(ok=True, output={})
        if name == "browser.assert_text":
            text = str(arguments.get("text", ""))
            try:
                await page.get_by_text(text).first.wait_for(timeout=5000)
            except Exception:
                return ToolResult(ok=False, error="text_not_found")
            return ToolResult(ok=True, output={"text": text})
        if name == "browser.check_a11y":
            violations = await page.evaluate(_A11Y_SCRIPT)
            return ToolResult(ok=True, output={"violations": violations})
        if name == "browser.accessibility_tree":
            try:
                tree = await page.accessibility.snapshot()
            except Exception:
                return ToolResult(ok=False, error="accessibility_tree_unavailable")
            return ToolResult(ok=True, output={"tree": tree})
        if name == "browser.screenshot":
            try:
                path = self._artifact_path(arguments.get("path"), "screenshot.png")
            except ValueError as exc:
                return ToolResult(ok=False, error=str(exc))
            path.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(path), full_page=True)
            return ToolResult(ok=True, output={"path": str(path)}, evidence=[str(path)])
        if name == "browser.console_log":
            path = self._write_artifact("console.json", self._console)
            return ToolResult(
                ok=True,
                output={"messages": self._console, "path": str(path)},
                evidence=[str(path)],
            )
        if name == "browser.network_log":
            path = self._write_artifact("network.json", self._network)
            return ToolResult(
                ok=True,
                output={"requests": self._network, "path": str(path)},
                evidence=[str(path)],
            )
        if name == "browser.start_trace":
            if self._browser is None:
                return ToolResult(ok=False, error="browser_not_started")
            await self._browser.start_tracing(screenshots=True)
            return ToolResult(ok=True, output={"trace": "started"})
        if name == "browser.stop_trace":
            if self._browser is None:
                return ToolResult(ok=False, error="browser_not_started")
            try:
                path = self._artifact_path(arguments.get("path"), "trace.zip")
            except ValueError as exc:
                return ToolResult(ok=False, error=str(exc))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(await self._browser.stop_tracing())
            return ToolResult(ok=True, output={"path": str(path)}, evidence=[str(path)])
        return ToolResult(ok=False, error=f"unknown_tool:{name}")

    def _artifact_path(self, value: Any, default: str) -> Path:
        """Resolve an artifact under the run workspace; never allow escapes."""

        raw = str(value or default)
        candidate = Path(raw)
        if candidate.is_absolute():
            raise ValueError("artifact_path_escape")
        root = self._workspace.resolve()
        path = (root / candidate).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("artifact_path_escape") from exc
        return path

    def _write_artifact(self, name: str, data: Any) -> Path:
        path = self._artifact_path(name, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, default=str))
        return path

    def _locator(self, page: Any, arguments: dict[str, Any]) -> Any:
        if arguments.get("test_id"):
            return page.get_by_test_id(str(arguments["test_id"]))
        role = arguments.get("role")
        name = arguments.get("name")
        if role and name:
            return page.get_by_role(str(role), name=str(name))
        raise ValueError("selector_fallback_blocked")

    def _check_network(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("invalid_navigation_url")
        if not self._allow_network:
            raise ValueError("network_egress_denied")
        if self._allowed_hosts and parsed.hostname not in self._allowed_hosts:
            raise ValueError("host_not_allowed")

    async def _page_or_start(self) -> Any:
        if self._page is not None:
            return self._page
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._page = await self._browser.new_page()
        self._page.on(
            "console",
            lambda message: self._console.append(
                {"type": message.type, "text": message.text[:500]}
            ),
        )
        self._page.on(
            "response",
            lambda response: self._network.append(
                {"status": response.status, "url": response.url[:500]}
            ),
        )
        return self._page

    async def close(self) -> None:
        self._closed = True
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        self._page = None


_A11Y_SCRIPT = """
() => {
  const elements = Array.from(document.querySelectorAll('a, button, input, select, textarea'));
  const violations = [];
  for (const el of elements) {
    const tag = el.tagName.toLowerCase();
    const text = (el.textContent || '').trim();
    const aria = (el.getAttribute('aria-label') || '').trim();
    const labelledBy = el.getAttribute('aria-labelledby');
    const title = (el.getAttribute('title') || '').trim();
    const alt = (el.getAttribute('alt') || '').trim();
    const hasLabel = Boolean(aria || labelledBy || title || alt || text);
    if (!hasLabel) {
      violations.push({
        tag,
        test_id: el.getAttribute('data-testid') || null,
        reason: 'missing_accessible_name'
      });
    }
  }
  return violations;
}
"""
