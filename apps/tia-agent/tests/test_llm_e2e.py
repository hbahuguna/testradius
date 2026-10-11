"""End-to-end: run `tia-agent llm test` against local mock provider servers.

Exercises the whole chain (CLI -> config -> credential store -> adapter ->
httpx -> response parsing) for all four providers, using fake user keys.
Purely local — no real provider or network access needed.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tia_agent.interfaces.cli import main

OPENAI_KEY = "sk-user-openai-e2e-000000000000"
ANTHROPIC_KEY = "sk-ant-user-e2e-000000000000"
GOOGLE_KEY = "AIzaUserE2eKey000000000000000000000000"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def _json(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        path = self.path

        if path == "/v1/chat/completions":                       # openai
            if self.headers.get("Authorization") != f"Bearer {OPENAI_KEY}":
                return self._json(401, {"error": "bad key"})
            return self._json(200, {"model": "gpt-4o-mini",
                                    "choices": [{"message": {"content": "OK"}}]})

        if path == "/v1/messages":                               # anthropic
            if self.headers.get("x-api-key") != ANTHROPIC_KEY:
                return self._json(401, {"error": "bad key"})
            return self._json(200, {"model": "claude-sonnet-4-5",
                                    "content": [{"type": "text", "text": "OK"}]})

        if path.endswith(":generateContent"):                    # google
            if self.headers.get("x-goog-api-key") != GOOGLE_KEY:
                return self._json(401, {"error": "bad key"})
            return self._json(200, {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]})

        if path == "/api/chat":                                  # ollama (no key)
            return self._json(200, {"model": "llama3.2",
                                    "message": {"content": "OK"}})

        return self._json(404, {"error": "not found"})


@pytest.fixture()
def provider_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture()
def iso(tmp_path, monkeypatch):
    monkeypatch.setenv("TIA_CREDENTIALS_BACKEND", "file")
    monkeypatch.setenv("TIA_CONFIG_HOME", str(tmp_path))
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
                 "GOOGLE_API_KEY", "TIA_LLM_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def _test_provider(provider, model, key, base_env, base_url, capsys, monkeypatch):
    args = ["llm", "set", "--provider", provider]
    if model:
        args += ["--model", model]
    if key:
        args += ["--key", key]
    assert main(args) == 0
    capsys.readouterr()

    monkeypatch.setenv(base_env, base_url)
    rc = main(["llm", "test"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "OK" in out, out


def test_openai_end_to_end(iso, provider_server, monkeypatch, capsys):
    _test_provider("openai", "gpt-4o-mini", OPENAI_KEY,
                   "OPENAI_BASE_URL", provider_server, capsys, monkeypatch)


def test_anthropic_end_to_end(iso, provider_server, monkeypatch, capsys):
    _test_provider("anthropic", "", ANTHROPIC_KEY,
                   "ANTHROPIC_BASE_URL", provider_server, capsys, monkeypatch)


def test_google_end_to_end(iso, provider_server, monkeypatch, capsys):
    _test_provider("google", "gemini-2.5-flash", GOOGLE_KEY,
                   "GOOGLE_BASE_URL", provider_server, capsys, monkeypatch)


def test_ollama_end_to_end(iso, provider_server, monkeypatch, capsys):
    _test_provider("ollama", "", "", "OLLAMA_HOST", provider_server, capsys, monkeypatch)


def test_wrong_key_surfaces_friendly_error(iso, provider_server, monkeypatch, capsys):
    assert main(["llm", "set", "--provider", "openai", "--key", "sk-wrong-key-000000000"]) == 0
    capsys.readouterr()
    monkeypatch.setenv("OPENAI_BASE_URL", provider_server)
    rc = main(["llm", "test"])
    err = capsys.readouterr().err
    assert rc == 7
    assert "rejected your API key" in err


def test_at_least_two_providers_verified_here(iso, provider_server, monkeypatch, capsys):
    """The AC: works with >=2 providers using user keys."""
    done = []
    _test_provider("openai", "gpt-4o-mini", OPENAI_KEY,
                   "OPENAI_BASE_URL", provider_server, capsys, monkeypatch)
    done.append("openai")
    _test_provider("anthropic", "", ANTHROPIC_KEY,
                   "ANTHROPIC_BASE_URL", provider_server, capsys, monkeypatch)
    done.append("anthropic")
    assert len(done) >= 2