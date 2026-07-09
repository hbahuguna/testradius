import asyncio
import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from .log_config import get_logger
from .session_context import SessionContextManager
from .context_injector import write_context_file
from apps.testradius.bridge.opencode import OpenCodeBridge

logger = get_logger("http")

from ..proxy.page_fetcher import PageFetcher
from ..proxy.dom_analyzer import DOMAnalyzer
from ..tia.git_analyzer import GitAnalyzer
from ..tia.test_mapper import TestMapper
from ..qwen.client import QwenClient


class _Handler(BaseHTTPRequestHandler):
    server_version = "testradius/0.1"

    def do_GET(self):
        self._start_time = time.perf_counter()
        if self.path == "/api/health":
            self._json({"status": "ok", "service": "testradius", "tools": self.server._tools})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        self._start_time = time.perf_counter()
        body = self._read_body()
        if self.path == "/api/proxy/fetch":
            self._handle_fetch(body)
        elif self.path == "/api/dom/analyze":
            self._handle_dom_analyze(body)
        elif self.path == "/api/tia/changed-files":
            self._handle_changed_files(body)
        elif self.path == "/api/tia/analyze":
            self._handle_tia_analyze(body)
        elif self.path == "/api/qwen/infer":
            self._handle_qwen_infer(body)
        elif self.path == "/api/files/save":
            self._handle_file_save(body)
        elif self.path == "/api/files/read":
            self._handle_file_read(body)
        elif self.path == "/api/session/init":
            self._handle_session_init(body)
        elif self.path == "/api/session/context":
            self._handle_session_context(body)
        elif self.path == "/api/session/record-action":
            self._handle_session_record_action(body)
        elif self.path == "/api/session/select-element":
            self._handle_session_select_element(body)
        elif self.path == "/api/session/test-code":
            self._handle_session_test_code(body)
        elif self.path == "/api/session/conversation":
            self._handle_session_conversation(body)
        elif self.path == "/api/agent_generate_test":
            self._handle_agent_generate_test(body)
        elif self.path == "/api/opencode/run":
            self._handle_opencode_run(body)
        elif self.path == "/api/session/clear":
            self._handle_session_clear(body)
        else:
            self._json({"error": f"not found: {self.path}"}, 404)

    def _json(self, data: dict, status: int = 200):
        self._status = status
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        elapsed = 0
        if hasattr(self, "_start_time"):
            elapsed = (time.perf_counter() - self._start_time) * 1000
        status = getattr(self, "_status", args[-1] if args else "?")
        logger.info("%s %s → %s (%.0fms)", self.command, self.path, status, elapsed)

    def _refresh_context(self, session_id: str | None = None):
        sid = session_id or getattr(self.server, "_session_id", None)
        if sid:
            ctx = self.server._sessions.to_dict(sid)
            write_context_file(sid, ctx)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        return json.loads(raw) if raw else {}

    def _handle_fetch(self, body: dict):
        url = body.get("url", "")
        if not url:
            self._json({"error": "url required"}, 400)
            return
        repo = self.server._repo_path
        fetcher = PageFetcher(repo_path=repo)
        import asyncio
        result = asyncio.run(fetcher.fetch(url))
        self._json(result)

    def _handle_dom_analyze(self, body: dict):
        html = body.get("html", "")
        url = body.get("url", "")
        if not html:
            self._json({"error": "html required"}, 400)
            return
        analyzer = DOMAnalyzer()
        result = analyzer.analyze(html, url=url)
        self._json(result)

    def _get_mapper() -> TestMapper:
        if not hasattr(self.server, "_mapper"):
            self.server._mapper = TestMapper(repo_path=self.server._repo_path)
        return self.server._mapper

    def _handle_changed_files(self, body: dict):
        repo = self.server._repo_path
        base = body.get("base", "main")
        git = GitAnalyzer(repo_path=repo)
        files = git.get_changed_files(base=base)
        diff = git.get_diff(base=base)
        self._json({"changed_files": files, "diff_length": len(diff)})

    def _handle_tia_analyze(self, body: dict):
        base = body.get("base", "main")
        git = GitAnalyzer(repo_path=self.server._repo_path)
        mapper = self._get_mapper()
        files = git.get_changed_files(base=base)
        result = mapper.analyze_impact(files)
        self._json(result)

    def _handle_qwen_infer(self, body: dict):
        prompt = body.get("prompt", "")
        if not prompt:
            self._json({"error": "prompt required"}, 400)
            return
        client = QwenClient()
        response = client.infer(prompt)
        self._json({"response": response})

    def _handle_opencode_run(self, body: dict):
        message = body.get("prompt", "") or body.get("message", "")
        model = body.get("model") or None
        session_id = body.get("session_id", "")
        if not message:
            self._json({"error": "prompt required"}, 400)
            return

        repo = self.server._repo_path

        async def _collect():
            events: list[dict] = []
            bridge = OpenCodeBridge(repo_path=repo, model=model)
            async for evt in bridge.run(message, model=model):
                events.append(evt)
            return events

        try:
            events = asyncio.run(_collect())
        except Exception as e:  # pragma: no cover - surfaced to caller
            logger.error("OpenCode run failed: %s", e)
            self._json({"error": str(e), "events": [], "code": ""}, 500)
            return

        code = "".join(e.get("content", "") for e in events if e.get("type") == "text")
        if session_id:
            self.server._sessions.set_test_code(
                session_id,
                code=code,
                language="typescript",
                description="OpenCode-generated test from workbench session",
            )
            self._refresh_context(session_id)

        self._json({"model": model, "events": events, "code": code})

    def _handle_file_save(self, body: dict):
        path = body.get("path", "")
        content = body.get("content", "")
        if not path or content is None:
            self._json({"error": "path and content required"}, 400)
            return
        repo = Path(self.server._repo_path)
        full_path = repo / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
        self._json({"saved": True, "path": path, "size": len(content)})

    def _handle_file_read(self, body: dict):
        path = body.get("path", "")
        if not path:
            self._json({"error": "path required"}, 400)
            return
        repo = Path(self.server._repo_path)
        full_path = repo / path
        if not full_path.exists() or not full_path.is_file():
            self._json({"error": "file not found", "path": path}, 404)
            return
        content = full_path.read_text()
        self._json({"content": content, "path": path, "size": len(content)})

    def _handle_session_init(self, body: dict):
        url = body.get("url", "")
        callers_id = body.get("session_id", "")
        session_id = self.server._sessions.create_session(url=url, session_id=callers_id)
        session = self.server._sessions.get_session(session_id)
        if session:
            repo = body.get("automation_repo", "")
            if repo:
                session.automation_repo = repo
        self._refresh_context(session_id)
        self._json({"session_id": session_id})

    def _handle_session_context(self, body: dict):
        session_id = body.get("session_id", "")
        if not session_id:
            self._json({"error": "session_id required"}, 400)
            return
        ctx = self.server._sessions.to_dict(session_id)
        if ctx is None:
            self._json({"error": "session not found"}, 404)
            return
        self._json(ctx)

    def _handle_session_record_action(self, body: dict):
        session_id = body.get("session_id", "")
        if not session_id:
            self._json({"error": "session_id required"}, 400)
            return
        ok = self.server._sessions.record_action(
            session_id,
            action_type=body.get("action_type", ""),
            selector=body.get("selector", ""),
            value=body.get("value", ""),
            url=body.get("url", ""),
        )
        if not ok:
            self._json({"error": "session not found"}, 404)
            return
        self._refresh_context(session_id)
        self._json({"ok": True})

    def _handle_session_select_element(self, body: dict):
        session_id = body.get("session_id", "")
        if not session_id:
            self._json({"error": "session_id required"}, 400)
            return
        ok = self.server._sessions.select_element(
            session_id,
            tag=body.get("tag", ""),
            text=body.get("text", ""),
            selector=body.get("selector", ""),
            attributes=body.get("attributes"),
        )
        if not ok:
            self._json({"error": "session not found"}, 404)
            return
        self._refresh_context(session_id)
        self._json({"ok": True})

    def _handle_session_test_code(self, body: dict):
        session_id = body.get("session_id", "")
        if not session_id:
            self._json({"error": "session_id required"}, 400)
            return
        ok = self.server._sessions.set_test_code(
            session_id,
            code=body.get("code", ""),
            language=body.get("language", ""),
            description=body.get("description", ""),
        )
        if not ok:
            self._json({"error": "session not found"}, 404)
            return
        self._refresh_context(session_id)
        self._json({"ok": True})

    def _handle_session_conversation(self, body: dict):
        session_id = body.get("session_id", "")
        if not session_id:
            self._json({"error": "session_id required"}, 400)
            return
        ok = self.server._sessions.add_message(
            session_id,
            role=body.get("role", "user"),
            content=body.get("content", ""),
        )
        if not ok:
            self._json({"error": "session not found"}, 404)
            return
        self._refresh_context(session_id)
        self._json({"ok": True})

    def _handle_session_clear(self, body: dict):
        session_id = body.get("session_id", "")
        if not session_id:
            self._json({"error": "session_id required"}, 400)
            return
        ok = self.server._sessions.clear_session(session_id)
        if not ok:
            self._json({"error": "session not found"}, 404)
            return
        self._refresh_context(session_id)
        self._json({"ok": True})


class LocalHTTPServer:
    def __init__(self, repo_path: str | Path = Path.cwd(), host: str = "127.0.0.1", port: int = 9800):
        self.host = host
        self.port = port
        self.repo_path = str(Path(repo_path).resolve())
        self._server: HTTPServer | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self):
        self._server = HTTPServer((self.host, self.port), _Handler)
        self._server._repo_path = self.repo_path
        self._server._sessions = SessionContextManager()
        self._server._tools = [
            "page_fetch", "dom_analyze",
            "tia_changed_files", "tia_analyze",
            "qwen_infer", "opencode_run",
            "file_save", "file_read",
            "session_init", "session_context",
            "session_record_action", "session_select_element",
            "session_test_code", "session_clear",
        ]
        session_id = self._server._sessions.create_session()
        self._server._session_id = session_id
        ctx = self._server._sessions.to_dict(session_id)
        write_context_file(session_id, ctx)
        self._server.serve_forever()

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

