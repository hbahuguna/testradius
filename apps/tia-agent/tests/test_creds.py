import json
import os
import subprocess
import sys

import pytest

from tia_agent.creds import CredentialStore, FileBackend, KeychainBackend, SecretToolBackend


class _FakeRunner:
    """Records commands; canned responses keyed by argv[0] + subcommand."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def __call__(self, args, input=None):
        self.calls.append({"args": list(args), "input": input})
        key = " ".join(args[:2])
        resp = self.responses.get(key, subprocess.CompletedProcess(args, 0, "", ""))
        if not isinstance(resp, subprocess.CompletedProcess):
            resp = subprocess.CompletedProcess(args, *resp)
        return resp


# ---------------------------------------------------------------------------
# file backend
# ---------------------------------------------------------------------------

def test_file_backend_roundtrip(tmp_path):
    backend = FileBackend(tmp_path / "credentials.json")
    assert backend.get("openai") is None
    backend.set("openai", "sk-abc")
    assert backend.get("openai") == "sk-abc"
    backend.set("anthropic", "ant-xyz")
    assert sorted(backend.list_providers()) == ["anthropic", "openai"]
    backend.delete("openai")
    assert backend.get("openai") is None
    assert backend.get("anthropic") == "ant-xyz"


def test_file_backend_is_0600(tmp_path):
    path = tmp_path / "credentials.json"
    FileBackend(path).set("openai", "sk-abc")
    mode = oct(path.stat().st_mode & 0o777)
    assert mode == "0o600"


def test_store_rejects_empty_key(tmp_path):
    with pytest.raises(ValueError):
        CredentialStore(backend="file", file_path=tmp_path / "c.json").set("openai", "   ")


def test_file_backend_survives_corrupt_json(tmp_path):
    path = tmp_path / "credentials.json"
    path.write_text("{not json")
    backend = FileBackend(path)
    assert backend.get("openai") is None
    backend.set("google", "gem-1")
    assert backend.get("google") == "gem-1"


# ---------------------------------------------------------------------------
# macOS keychain backend (fake runner — never touches the real keychain)
# ---------------------------------------------------------------------------

def test_keychain_set_reads_key_from_stdin_not_argv():
    runner = _FakeRunner()
    KeychainBackend(runner).set("openai", "sk-abc")
    call = runner.calls[0]
    # key travels via stdin (entered + retyped) so it never shows up in `ps`
    assert call["input"] == "sk-abc\nsk-abc\n"
    assert "sk-abc" not in call["args"]
    assert call["args"][:3] == ["security", "add-generic-password", "-U"]
    assert "-X" not in call["args"]
    assert "tia-agent" in call["args"]
    assert "openai" in call["args"]


def test_keychain_get_parses_stdout():
    runner = _FakeRunner(responses={
        "security find-generic-password": subprocess.CompletedProcess(
            [], 0, "sk-from-keychain\n", ""),
        "security delete-generic-password": subprocess.CompletedProcess([], 0, "", ""),
    })
    backend = KeychainBackend(runner)
    assert backend.get("openai") == "sk-from-keychain"
    backend.delete("openai")
    assert runner.calls[1]["args"][:1] == ["security"]


def test_keychain_get_missing_entry_returns_none():
    runner = _FakeRunner(responses={
        "security find-generic-password": subprocess.CompletedProcess([], 1, "", "not found"),
    })
    assert KeychainBackend(runner).get("openai") is None


def test_keychain_set_failure_raises():
    runner = _FakeRunner(responses={
        "security add-generic-password": subprocess.CompletedProcess([], 1, "", "denied"),
    })
    with pytest.raises(RuntimeError, match="keychain write failed"):
        KeychainBackend(runner).set("openai", "k")


# ---------------------------------------------------------------------------
# linux secret-tool backend (fake runner)
# ---------------------------------------------------------------------------

def test_secret_tool_set_passes_key_via_stdin():
    runner = _FakeRunner()
    SecretToolBackend(runner).set("anthropic", "ant-abc")
    call = runner.calls[0]
    assert call["input"] == "ant-abc"
    assert "ant-abc" not in call["args"]
    assert call["args"][:2] == ["secret-tool", "store"]
    assert "tia-agent" in call["args"]


def test_secret_tool_get_missing_returns_none():
    runner = _FakeRunner(responses={
        "secret-tool lookup": subprocess.CompletedProcess([], 1, "", ""),
    })
    assert SecretToolBackend(runner).get("anthropic") is None


# ---------------------------------------------------------------------------
# CredentialStore backend selection
# ---------------------------------------------------------------------------

def test_store_forces_file_backend_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TIA_CREDENTIALS_BACKEND", "file")
    monkeypatch.setenv("TIA_CONFIG_HOME", str(tmp_path))
    store = CredentialStore()
    assert store.backend_name == "file"
    store.set("openai", "sk-env-selected")
    assert (tmp_path / "credentials.json").exists()
    assert CredentialStore().get("openai") == "sk-env-selected"


def test_store_explicit_backend_wins_over_env(monkeypatch):
    monkeypatch.setenv("TIA_CREDENTIALS_BACKEND", "file")
    store = CredentialStore(backend="keychain")
    assert store.backend_name == "keychain"


def test_config_json_never_contains_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("TIA_CREDENTIALS_BACKEND", "file")
    monkeypatch.setenv("TIA_CONFIG_HOME", str(tmp_path))
    from tia_agent.config import TiaConfig

    store = CredentialStore()
    store.set("openai", "sk-should-not-leak")
    cfg = TiaConfig(llm_provider="openai", llm_model="gpt-4o-mini")
    cfg.save()
    text = (tmp_path / "config.json").read_text()
    assert "sk-should-not-leak" not in text
    assert "api_key" not in json.loads(text)


@pytest.mark.skipif(
    not (sys.platform == "darwin" and os.environ.get("TIA_KEYCHAIN_TEST")),
    reason="set TIA_KEYCHAIN_TEST=1 to exercise the real macOS keychain",
)
def test_real_keychain_roundtrip():
    """Opt-in: writes a throwaway item to the login keychain, then removes it."""
    backend = KeychainBackend()
    try:
        backend.set("e2e-probe", "sk-real-keychain-roundtrip-999")
        assert backend.get("e2e-probe") == "sk-real-keychain-roundtrip-999"
    finally:
        backend.delete("e2e-probe")
    assert backend.get("e2e-probe") is None