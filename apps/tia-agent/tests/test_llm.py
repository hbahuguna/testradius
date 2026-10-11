import json

import httpx
import pytest

from tia_agent.config import TiaConfig
from tia_agent.creds import CredentialStore
from tia_agent.llm import (
    DEFAULT_MODELS,
    ENV_KEYS,
    PROVIDERS,
    LLMError,
    LLMAuthError,
    get_adapter,
    llm_status,
    resolve_api_key,
)
from tia_agent.llm.adapters import (
    AnthropicAdapter,
    GoogleAdapter,
    OllamaAdapter,
    OpenAIAdapter,
)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _capturing(handler, store):
    calls = {}

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls["request"] = request
        return handler(request)

    return _client(wrapped), calls


# ---------------------------------------------------------------------------
# request shaping per provider
# ---------------------------------------------------------------------------

def test_openai_request_and_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.openai.com/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer user-key-123"
        body = json.loads(request.content)
        assert body["model"] == "gpt-4o-mini"
        assert body["messages"] == [{"role": "user", "content": "hi"}]
        return httpx.Response(200, json={
            "model": "gpt-4o-mini",
            "choices": [{"message": {"role": "assistant", "content": "hello"}}],
            "usage": {"total_tokens": 9},
        })

    adapter = OpenAIAdapter(api_key="user-key-123", client=_client(handler))
    resp = adapter.chat([{"role": "user", "content": "hi"}])
    assert resp.text == "hello"
    assert resp.provider == "openai"
    assert resp.usage["total_tokens"] == 9


def test_anthropic_request_and_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.anthropic.com/v1/messages"
        assert request.headers["x-api-key"] == "ant-key-456"
        assert request.headers["anthropic-version"] == "2023-06-01"
        body = json.loads(request.content)
        assert body["model"] == "claude-sonnet-4-5"
        assert body["max_tokens"] == 4096
        assert body["system"] == "be terse"
        # system role must NOT leak into messages (API rejects it)
        assert all(m["role"] in ("user", "assistant") for m in body["messages"])
        return httpx.Response(200, json={
            "model": "claude-sonnet-4-5",
            "content": [{"type": "text", "text": "hi there"}],
            "usage": {"output_tokens": 3},
        })

    adapter = AnthropicAdapter(api_key="ant-key-456", client=_client(handler))
    resp = adapter.chat([
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "hi"},
    ])
    assert resp.text == "hi there"
    assert resp.provider == "anthropic"


def test_google_request_and_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
        )
        assert request.headers["x-goog-api-key"] == "g-key-789"
        body = json.loads(request.content)
        roles = [c["role"] for c in body["contents"]]
        assert roles == ["model", "user"]
        assert body["systemInstruction"]["parts"][0]["text"] == "sys"
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": "gemini says hi"}]}}],
            "usageMetadata": {"totalTokenCount": 5},
        })

    adapter = GoogleAdapter(api_key="g-key-789", client=_client(handler))
    resp = adapter.chat([
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "earlier"},
        {"role": "user", "content": "hi"},
    ])
    assert resp.text == "gemini says hi"
    assert resp.provider == "google"


def test_ollama_request_needs_no_key():
    def handler(request: httpx.Request) -> httpx.Request:
        assert request.url == "http://localhost:11434/api/chat"
        assert "Authorization" not in request.headers
        assert "x-api-key" not in request.headers
        body = json.loads(request.content)
        assert body["stream"] is False
        assert body["model"] == "llama3.2"
        return httpx.Response(200, json={"model": "llama3.2",
                                         "message": {"content": "local ok"}})

    adapter = OllamaAdapter(api_key="", client=_client(lambda r: handler(r)))
    resp = adapter.chat([{"role": "user", "content": "hi"}])
    assert resp.text == "local ok"


# ---------------------------------------------------------------------------
# error mapping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("adapter_cls", [OpenAIAdapter, AnthropicAdapter, GoogleAdapter])
def test_bad_key_maps_to_auth_error(adapter_cls):
    client = _client(lambda r: httpx.Response(401, text="bad key"))
    adapter = adapter_cls(api_key="wrong", client=client)
    with pytest.raises(LLMAuthError) as e:
        adapter.chat([{"role": "user", "content": "x"}])
    assert "rejected your API key" in str(e.value)
    assert "llm set" in str(e.value)


def test_rate_limit_and_5xx_map_to_unavailable():
    from tia_agent.llm.base import LLMUnavailableError

    client = _client(lambda r: httpx.Response(429, text="slow down"))
    with pytest.raises(LLMUnavailableError):
        OpenAIAdapter(api_key="k", client=client).chat([{"role": "user", "content": "x"}])

    client = _client(lambda r: httpx.Response(503, text="nope"))
    with pytest.raises(LLMUnavailableError):
        OpenAIAdapter(api_key="k", client=client).chat([{"role": "user", "content": "x"}])


def test_connection_error_maps_to_unavailable():
    from tia_agent.llm.base import LLMUnavailableError

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(LLMUnavailableError) as e:
        OllamaAdapter(client=_client(boom)).chat([{"role": "user", "content": "x"}])
    assert "ollama unreachable" in str(e.value)


# ---------------------------------------------------------------------------
# key resolution + adapter factory (env > credential store)
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("TIA_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("TIA_CREDENTIALS_BACKEND", "file")
    for name in (*ENV_KEYS.values(), "GOOGLE_API_KEY"):
        if name:
            monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_key_resolution_prefers_env_over_store(isolated):
    store = CredentialStore()
    store.set("openai", "from-store")
    assert resolve_api_key("openai", store) == "from-store"
    import os

    os.environ["OPENAI_API_KEY"] = "from-env"
    try:
        assert resolve_api_key("openai", store) == "from-env"
    finally:
        del os.environ["OPENAI_API_KEY"]


def test_get_adapter_wires_keys_for_multiple_providers(isolated):
    store = CredentialStore()
    store.set("openai", "sk-user-1")
    store.set("anthropic", "ant-user-2")
    store.set("google", "gem-user-3")

    cfg = TiaConfig(llm_provider="openai", llm_model="gpt-x")
    a = get_adapter(cfg, store)
    assert (a.provider, a.api_key, a.model) == ("openai", "sk-user-1", "gpt-x")

    cfg2 = TiaConfig(llm_provider="anthropic")
    a2 = get_adapter(cfg2, store)
    assert (a2.provider, a2.api_key, a2.model) == ("anthropic", "ant-user-2",
                                                   DEFAULT_MODELS["anthropic"])

    cfg3 = TiaConfig(llm_provider="google")
    a3 = get_adapter(cfg3, store)
    assert (a3.provider, a3.api_key) == ("google", "gem-user-3")


def test_ollama_needs_no_key(isolated):
    cfg = TiaConfig(llm_provider="ollama")
    a = get_adapter(cfg, CredentialStore())
    assert a.provider == "ollama"
    assert a.api_key == ""


def test_missing_key_raises_with_guidance(isolated):
    cfg = TiaConfig(llm_provider="openai")
    with pytest.raises(LLMError) as e:
        get_adapter(cfg, CredentialStore())
    assert "OPENAI_API_KEY" in str(e.value)
    assert "llm set" in str(e.value)


def test_unknown_provider_rejected():
    with pytest.raises(LLMError):
        get_adapter(TiaConfig(llm_provider="mistral"), CredentialStore())


# ---------------------------------------------------------------------------
# status: reports source, never the key
# ---------------------------------------------------------------------------

def test_llm_status_never_contains_the_key(isolated):
    store = CredentialStore()
    store.set("openai", "sk-super-secret-user-key")
    cfg = TiaConfig(llm_provider="openai", llm_model="gpt-4o-mini")
    info = llm_status(cfg, store)
    assert info["key_source"] == "file"
    assert info["key_present"] is True
    assert "sk-super-secret-user-key" not in json.dumps(info)


def test_llm_status_reports_missing(isolated):
    cfg = TiaConfig(llm_provider="anthropic")
    info = llm_status(cfg, CredentialStore())
    assert info["key_source"] == "MISSING"
    assert info["key_present"] is False


def test_all_providers_have_defaults():
    assert set(PROVIDERS) == {"openai", "anthropic", "google", "ollama"}
    assert all(DEFAULT_MODELS.values())