import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from ..proxy.page_fetcher import PageFetcher
from ..proxy.dom_analyzer import DOMAnalyzer
from ..tia.git_analyzer import GitAnalyzer
from ..tia.test_mapper import TestMapper
from ..qwen.client import QwenClient


class _Handler(BaseHTTPRequestHandler):
    server_version = "testradius/0.1"

    def do_GET(self):
        if self.path == "/api/health":
            self._json({"status": "ok", "service": "testradius", "tools": self.server._tools})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
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
        else:
            self._json({"error": f"not found: {self.path}"}, 404)

    def _json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

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

    def _get_mapper(self) -> TestMapper:
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
        self._server._tools = [
            "page_fetch", "dom_analyze",
            "tia_changed_files", "tia_analyze",
            "qwen_infer",
            "file_save", "file_read",
        ]
        self._server.serve_forever()

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
