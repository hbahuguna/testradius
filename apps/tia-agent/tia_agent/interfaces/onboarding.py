"""First-run onboarding: guided LLM provider + key setup.

Runs when the REPL starts with no provider configured. Saves only the
provider/model choice to config.json; the key goes to the credential store.
Skip with TIA_SKIP_ONBOARDING=1 (CI/non-interactive).
"""

from __future__ import annotations

import getpass
import os
import sys
from typing import Callable, List, Optional

from ..config import TiaConfig
from ..creds import CredentialStore
from ..llm import DEFAULT_MODELS, ENV_KEYS, PROVIDERS
from ..llm.base import LLMError

InputFn = Callable[[str], str]
GetPassFn = Callable[[str], str]

MENU = """\
Choose your LLM provider (BYO key — nothing is bundled or shared):
  1) openai    2) anthropic    3) google    4) ollama (local, no key)
"""


def onboarding_needed(config: TiaConfig) -> bool:
    if os.environ.get("TIA_SKIP_ONBOARDING"):
        return False
    if config.llm_provider:
        return False
    # Env-configured providers (CI) don't need the prompt either.
    if os.environ.get("TIA_LLM_PROVIDER"):
        return False
    return sys.stdin.isatty()


def run_onboarding(
    config: TiaConfig,
    store: Optional[CredentialStore] = None,
    *,
    input_fn: InputFn = input,
    getpass_fn: GetPassFn = getpass.getpass,
) -> bool:
    """Interactive first-run setup. Returns True if a provider was configured."""
    store = store or CredentialStore()
    print(MENU)
    choice = _ask_choice(input_fn)
    if choice is None:
        print("Skipped — run `tia-agent llm set` any time.")
        return False
    provider = PROVIDERS[choice - 1]
    default_model = DEFAULT_MODELS[provider]
    model = input_fn(f"model [{default_model}]: ").strip() or default_model

    key = ""
    if provider != "ollama":
        key = getpass_fn(f"{provider} API key (hidden, empty to skip): ").strip()
        if key:
            store.set(provider, key)
            print(f"Key stored in {store.backend_name}.")
        else:
            print("No key stored — you'll be prompted when first needed.")
    else:
        print("ollama runs locally — no API key required.")

    config.llm_provider = provider
    config.llm_model = model
    path = config.save()
    print(f"Saved {provider}/{model} -> {path}")
    return True


def _ask_choice(input_fn: InputFn) -> Optional[int]:
    raw = input_fn("provider number (1-4, empty to skip): ").strip()
    if not raw:
        return None
    if raw.isdigit() and 1 <= int(raw) <= len(PROVIDERS):
        return int(raw)
    # Also accept the provider name directly.
    name = raw.lower()
    if name in PROVIDERS:
        return PROVIDERS.index(name) + 1
    print(f"Unrecognized choice '{raw}'.")
    return None