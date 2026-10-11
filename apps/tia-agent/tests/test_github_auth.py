"""E3/T3: GitHub token resolution, storage, and hidden prompting."""

import types

import pytest

from tia_agent.config import TiaConfig
from tia_agent.creds import CredentialStore
from tia_agent.interfaces import github_auth


@pytest.fixture
def store(tmp_path):
    return CredentialStore(backend="file", file_path=tmp_path / "credentials.json")


def test_resolve_from_config(store):
    cfg = TiaConfig(github_token="cfg-tok")
    assert github_auth.resolve_github_token(cfg, store) == "cfg-tok"


def test_resolve_from_env(store, monkeypatch):
    monkeypatch.setenv("TIA_GITHUB_TOKEN", "env-tok")
    assert github_auth.resolve_github_token(None, store) == "env-tok"


def test_resolve_from_store(store):
    store.set("github", "store-tok")
    assert github_auth.resolve_github_token(None, store) == "store-tok"


def test_token_source_missing_then_store(store, monkeypatch):
    monkeypatch.delenv("TIA_GITHUB_TOKEN", raising=False)
    assert github_auth.token_source(None, store) == "MISSING"
    store.set("github", "store-tok")
    assert github_auth.token_source(None, store) == "file"


def test_ensure_returns_existing(store):
    store.set("github", "store-tok")
    assert github_auth.ensure_github_token(None, store) == "store-tok"


def test_ensure_no_prompt_returns_none(store):
    assert github_auth.ensure_github_token(None, store, allow_prompt=False) is None


def test_ensure_prompts_when_tty(store, monkeypatch):
    monkeypatch.setattr(github_auth.sys, "stdin", types.SimpleNamespace(isatty=lambda: True))
    token = github_auth.ensure_github_token(
        None, store, getpass_fn=lambda _prompt: "prompted-tok"
    )
    assert token == "prompted-tok"
    assert store.get("github") == "prompted-tok"


def test_prompt_skipped_when_not_tty(store, monkeypatch):
    monkeypatch.setattr(github_auth.sys, "stdin", types.SimpleNamespace(isatty=lambda: False))
    assert github_auth.prompt_github_token(store, getpass_fn=lambda _p: "x") is None
    assert store.get("github") is None


def test_prompt_empty_is_none(store, monkeypatch):
    monkeypatch.setattr(github_auth.sys, "stdin", types.SimpleNamespace(isatty=lambda: True))
    assert github_auth.prompt_github_token(store, getpass_fn=lambda _p: "  ") is None
