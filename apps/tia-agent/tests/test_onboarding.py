import json

import pytest

from tia_agent.config import TiaConfig
from tia_agent.creds import CredentialStore
from tia_agent.interfaces.onboarding import onboarding_needed, run_onboarding


class _Inputs:
    def __init__(self, *lines):
        self._lines = list(lines)

    def __call__(self, prompt=""):
        if not self._lines:
            raise EOFError
        return self._lines.pop(0)


@pytest.fixture()
def store(tmp_path):
    return CredentialStore(backend="file", file_path=tmp_path / "credentials.json")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("TIA_SKIP_ONBOARDING", raising=False)
    monkeypatch.delenv("TIA_LLM_PROVIDER", raising=False)


# ---------------------------------------------------------------------------
# when do we prompt?
# ---------------------------------------------------------------------------

def test_needed_when_unconfigured_on_tty(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    assert onboarding_needed(TiaConfig()) is True


def test_not_needed_when_provider_configured(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    assert onboarding_needed(TiaConfig(llm_provider="openai")) is False


def test_not_needed_when_env_provider_set(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setenv("TIA_LLM_PROVIDER", "anthropic")
    assert onboarding_needed(TiaConfig()) is False


def test_not_needed_when_skip_flag_set(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setenv("TIA_SKIP_ONBOARDING", "1")
    assert onboarding_needed(TiaConfig()) is False


def test_not_needed_when_not_a_tty(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    assert onboarding_needed(TiaConfig()) is False


# ---------------------------------------------------------------------------
# the prompt flow
# ---------------------------------------------------------------------------

def test_openai_flow_stores_key_and_saves_config(tmp_path, monkeypatch, store):
    cfg = TiaConfig()
    monkeypatch.setenv("TIA_CONFIG_HOME", str(tmp_path))
    ok = run_onboarding(
        cfg, store,
        input_fn=_Inputs("1", "gpt-4o-mini"),     # provider=openai, model
        getpass_fn=lambda p: "sk-user-secret",
    )
    assert ok is True
    assert cfg.llm_provider == "openai"
    assert cfg.llm_model == "gpt-4o-mini"
    assert store.get("openai") == "sk-user-secret"
    # key never lands in config.json
    assert "sk-user-secret" not in (tmp_path / "config.json").read_text()


def test_provider_name_accepted_instead_of_number(tmp_path, monkeypatch, store):
    cfg = TiaConfig()
    monkeypatch.setenv("TIA_CONFIG_HOME", str(tmp_path))
    run_onboarding(cfg, store, input_fn=_Inputs("anthropic", ""),
                   getpass_fn=lambda p: "ant-key")
    assert cfg.llm_provider == "anthropic"
    assert cfg.llm_model == "claude-sonnet-4-5"   # default


def test_ollama_flow_needs_no_key(tmp_path, monkeypatch, store):
    cfg = TiaConfig()
    monkeypatch.setenv("TIA_CONFIG_HOME", str(tmp_path))
    prompts = []

    def fake_getpass(prompt):
        prompts.append(prompt)
        raise AssertionError("ollama must not prompt for a key")

    run_onboarding(cfg, store, input_fn=_Inputs("4", ""), getpass_fn=fake_getpass)
    assert cfg.llm_provider == "ollama"
    assert cfg.llm_model == "llama3.2"
    assert prompts == []


def test_blank_choice_skips_without_writing(tmp_path, monkeypatch, store):
    cfg = TiaConfig()
    monkeypatch.setenv("TIA_CONFIG_HOME", str(tmp_path))
    ok = run_onboarding(cfg, store, input_fn=_Inputs(""), getpass_fn=lambda p: "x")
    assert ok is False
    assert cfg.llm_provider == ""
    assert not (tmp_path / "config.json").exists()


def test_invalid_choice_skips(tmp_path, monkeypatch, store):
    cfg = TiaConfig()
    monkeypatch.setenv("TIA_CONFIG_HOME", str(tmp_path))
    ok = run_onboarding(cfg, store, input_fn=_Inputs("banana"), getpass_fn=lambda p: "x")
    assert ok is False
    assert cfg.llm_provider == ""


def test_key_can_be_left_empty_and_configured_later(tmp_path, monkeypatch, store):
    cfg = TiaConfig()
    monkeypatch.setenv("TIA_CONFIG_HOME", str(tmp_path))
    run_onboarding(cfg, store, input_fn=_Inputs("2", ""), getpass_fn=lambda p: "")
    assert cfg.llm_provider == "anthropic"
    assert store.get("anthropic") is None