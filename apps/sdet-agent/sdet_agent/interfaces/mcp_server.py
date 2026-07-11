"""MCP server: expose the tool registry over STDIO and SSE transports.

Implements the Model Context Protocol as JSON-RPC 2.0 (textbook Ch.3). The
same ToolRegistry used for direct in-process calls is surfaced to any MCP
client (OpenCode, Claude, custom). Switching transports is a one-line swap
between `run_stdio()` and `run_sse()` — the server logic is identical.

Dependency-free: stdio uses stdlib; SSE uses a tiny stdlib HTTP server so the
MCP surface works without the optional `mcp`/`fastapi` packages.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from ..tools.registry import ToolRegistry

from ..tools import build_registry # Import build_registry

logger = logging.getLogger("sdet_agent.mcp")

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "sdet-agent", "version": "0.1.0"}


class MCPServer:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    # --- JSON-RPC handling (transport-agnostic) ---------------------------

    def handle(self, msg: dict[str, Any]) -> Optional[dict[str, Any]]:
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if method == "initialize":
            return self._resp(msg_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            })
        if method == "tools/list":
            tools = [t.to_mcp() for t in self.registry.list_specs()]
            return self._resp(msg_id, {"tools": tools})
        if method == "tools/call":
            name = params.get("name", "")
            arguments = params.get("arguments") or {}
            try:
                result = self.registry.call(name, arguments)
                return self._resp(msg_id, {
                    "content": [{"type": "text", "text": self._stringify(result)}],
                    "isError": False,
                })
            except Exception as exc:  # noqa: BLE001
                return self._resp(msg_id, {
                    "content": [{"type": "text", "text": f"[tool error] {exc}"}],
                    "isError": True,
                })
        if method == "ping":
            return self._resp(msg_id, {})
        if method and method.startswith("notifications/"):
            return None  # notifications require no response
        return self._resp(msg_id, None) if msg_id is not None else None

    @staticmethod
    def _resp(msg_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _stringify(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, indent=2, default=str)

    # --- STDIO transport ---------------------------------------------------

    def run_stdio(self) -> None:
        """Read line-delimited JSON-RPC from stdin, write to stdout."""
        import sys

        logger.info("MCP server (stdio) starting")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            response = self.handle(msg)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

    # --- SSE transport -----------------------------------------------------

    def run_sse(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        """HTTP SSE server: GET /sse streams server->client, POST /messages receives client->server."""
        subscribers: list[threading.Event] = []
        queue: list[str] = []
        lock = threading.Lock()

        def publish(payload: str) -> None:
            with lock:
                queue.append(payload)
                for ev in subscribers:
                    ev.set()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence default logging
                pass

            def do_GET(self):
                if self.path == "/sse":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    ev = threading.Event()
                    with lock:
                        subscribers.append(ev)
                    # initial endpoint event (MCP SSE handshake)
                    self.wfile.write(b"event: endpoint\ndata: /messages\n\n")
                    self.wfile.flush()
                    try:
                        while True:
                            with lock:
                                while queue:
                                    item = queue.pop(0)
                                    self.wfile.write(f"event: message\ndata: {item}\n\n".encode())
                                    self.wfile.flush()
                            if ev.wait(timeout=30):
                                ev.clear()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    finally:
                        with lock:
                            if ev in subscribers:
                                subscribers.remove(ev)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                if self.path == "/messages":
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length) if length else b"{}"
                    try:
                        msg = json.loads(body or b"{}")
                    except json.JSONDecodeError:
                        msg = {}
                    response = self.server.mcp.handle(msg)  # type: ignore[attr-defined]
                    if response is not None:
                        publish(json.dumps(response))
                    self.send_response(202)
                    self.end_headers()
                else:
                    self.send_response(404)
                    self.end_headers()

        httpd = ThreadingHTTPServer((host, port), Handler)
        httpd.mcp = self  # type: ignore[attr-defined]
        logger.info("MCP server (sse) on http://%s:%s/sse", host, port)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()
