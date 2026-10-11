"""GitHub token acquisition for private-repo intake (E3/T3).

Precedence: ``config.github_token`` / ``TIA_GITHUB_TOKEN`` -> credential store
(provider ``github``) -> interactive hidden prompt (stored for next time).
Tokens never touch config.json, logs, or argv.
"""

from __future__ import annotations

import getpass
import os
import sys
from typing import Callable, Optional

from ..config import TiaConfig
from ..creds import CredentialStore

PROVIDER = "github"
GetPassFn = Callable[[str], str]

DEFAULT_PROMPT = (
    "GitHub token (hidden; needs 'repo' scope for private repos, empty to skip): "
)


def token_source(config: Optional[TiaConfig] = None, store: Optional[CredentialStore] = None) -> str:
    """Where a token would come from: ``env`` | backend name | ``MISSING``."""
    if config is not None and config.github_token:
        return "env"
    if os.environ.get("TIA_GITHUB_TOKEN"):
        return "env"
    store = store or CredentialStore()
    if store.get(PROVIDER):
        return store.backend_name
    return "MISSING"


def resolve_github_token(config: Optional[TiaConfig] = None,
                         store: Optional[CredentialStore] = None) -> Optional[str]:
    """Return a token from config/env or the credential store, else None."""
    if config is not None and config.github_token:
        return config.github_token.strip() or None
    env = os.environ.get("TIA_GITHUB_TOKEN")
    if env and env.strip():
        return env.strip()
    store = store or CredentialStore()
    return store.get(PROVIDER)


def store_github_token(token: str, store: Optional[CredentialStore] = None) -> None:
    (store or CredentialStore()).set(PROVIDER, token.strip())


def prompt_github_token(
    store: Optional[CredentialStore] = None,
    *,
    getpass_fn: Optional[GetPassFn] = None,
    prompt: str = DEFAULT_PROMPT,
) -> Optional[str]:
    """Always ask (hidden) for a token and store it. Returns None if skipped."""
    getpass_fn = getpass_fn or getpass.getpass
    if not sys.stdin.isatty():
        return None
    token = (getpass_fn(prompt) or "").strip()
    if not token:
        return None
    store_github_token(token, store)
    return token


def ensure_github_token(
    config: Optional[TiaConfig] = None,
    store: Optional[CredentialStore] = None,
    *,
    getpass_fn: Optional[GetPassFn] = None,
    allow_prompt: bool = True,
    prompt: str = DEFAULT_PROMPT,
) -> Optional[str]:
    """Resolve a token, prompting (once) when none is configured."""
    token = resolve_github_token(config, store)
    if token:
        return token
    if not allow_prompt:
        return None
    return prompt_github_token(store, getpass_fn=getpass_fn, prompt=prompt)
