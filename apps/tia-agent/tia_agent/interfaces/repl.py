"""Conversational REPL for `tia-agent`.

A1 ships a deterministic conversation loop (intake Q&A, step explanation,
instrumentation gate) that the LLM-guided layer (A3) will drive on top of.
Every user-facing action goes through the same pipeline as `tia-agent analyze`.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Callable, Optional

from ..analyze import AnalyzeRunner
from ..config import TiaConfig
from ..errors import TiaError

BANNER = """\
tia-agent — conversational Test Impact Analysis
Type `help` for commands, `quit` to exit."""

HELP = """\
Commands:
  activate KEY                Activate this machine with a license key
  analyze REPO PR             Run TIA on owner/repo PR <n>
    e.g.: analyze hbahuguna/py-key-value 12
  llm                         Show LLM provider / key source
  status                      Show license status
  doctor                      Check license + backend connectivity
  config show                 Show effective configuration
  help                        This message
  quit / exit                 Leave the agent

You can also just describe what you want, e.g.
  "which tests are affected by the login change in acme/shop PR 42?"
"""


@dataclass
class _Interpreted:
    verb: str
    args: list[str]


class Repl:
    def __init__(self, config: TiaConfig, *, input_fn: Optional[Callable[[str], str]] = None,
                 output_fn: Optional[Callable[[str], None]] = None, runner_factory=None,
                 getpass_fn: Optional[Callable[[str], str]] = None,
                 flow_factory=None):
        self.config = config
        self._input = input_fn or input
        self._print = output_fn or print
        self._getpass = getpass_fn
        self._runner_factory = runner_factory or (lambda c: AnalyzeRunner.build(c))
        self._flow_factory = flow_factory
        self._flow = None
        self._running = True

    # -- entry --------------------------------------------------------------
    def run(self) -> int:
        self._maybe_onboard()
        self._print(BANNER)
        try:
            while self._running:
                try:
                    line = self._input("tia> ").strip()
                except (EOFError, KeyboardInterrupt):
                    self._print("\nBye.")
                    return 0
                if not line:
                    continue
                if self._dispatch(line) is False:
                    return 0
        finally:
            pass
        return 0

    # -- first-run onboarding ----------------------------------------------
    def _maybe_onboard(self) -> None:
        from .onboarding import onboarding_needed, run_onboarding

        if not onboarding_needed(self.config):
            return
        self._print("First run — set up your LLM provider (BYO key, never bundled).")
        kwargs = {"input_fn": self._input}
        if self._getpass is not None:
            kwargs["getpass_fn"] = self._getpass
        run_onboarding(self.config, **kwargs)

    # -- dispatch -----------------------------------------------------------
    def _dispatch(self, line: str):
        # Stop conditions.
        if line in ("quit", "exit"):
            self._print("Bye.")
            self._running = False
            return False

        # Strip trailing `?` and punctuation for friendlier parsing.
        cleaned = line.rstrip("?!.").strip()
        if cleaned in ("help", "h", "?"):
            self._print(HELP)
            return True
        if cleaned == "status":
            return self._do_status()
        if cleaned == "doctor":
            return self._do_doctor()
        if cleaned in ("config show", "cf"):
            return self._do_config_show()
        if cleaned == "llm":
            return self._do_llm_show()

        interp = _interpret(cleaned)
        if interp is None:
            return self._do_converse(cleaned)
        try:
            if interp.verb == "activate":
                return self._do_activate(interp.args[0])
            if interp.verb == "analyze":
                if len(interp.args) < 2:
                    self._print("Usage: analyze OWNER/REPO PR")
                    return True
                return self._do_analyze(interp.args[0], interp.args[1])
        except TiaError as e:
            self._print(f"error: {e}")
            return True
        self._print("Unknown command. Try `help`.")
        return True

    # -- conversational flow (A3) -------------------------------------------
    def _get_flow(self):
        if self._flow is None:
            from ..conversation import ConversationFlow, build_llm

            ui = _ReplUI(self._input, self._print)
            if self._flow_factory is not None:
                self._flow = self._flow_factory(ui)
            else:
                runner = self._runner_factory(self.config)
                self._flow = ConversationFlow(
                    self.config, runner, ui, llm=build_llm(self.config),
                    token_prompt=self._github_token_prompt,
                )
        return self._flow

    def _github_token_prompt(self):
        from ..creds import CredentialStore
        from .github_auth import prompt_github_token

        return prompt_github_token(CredentialStore(), getpass_fn=self._getpass)

    def _do_converse(self, text: str) -> bool:
        from ..conversation.intake import looks_like_request

        # Bare greetings shouldn't trigger intake; guide instead.
        if not looks_like_request(text) and not re.search(r"[\w.-]+/[\w.-]+|#\d+|\bpr\s*\d+", text, re.I):
            self._print("I run Test Impact Analysis. Try `analyze OWNER/REPO PR`, "
                        "or describe the change in plain English.")
            return True
        try:
            self._get_flow().handle(text)
        except TiaError as e:
            self._print(f"error: {e}")
        except Exception as e:  # noqa: BLE001 - keep the REPL alive
            self._print(f"error: {e}")
        return True

    # -- actions ------------------------------------------------------------
    def _do_activate(self, key: str) -> bool:
        from ..license_guard import LicenseGuard

        guard = LicenseGuard(self.config)
        info = guard.activate(key)
        self._print(f"Activated. subscription={info['subscription_status']} quota_remaining={info['quota_remaining']}")
        return True

    def _do_status(self) -> bool:
        from ..license_guard import LicenseGuard

        info = LicenseGuard(self.config).status()
        self._print(f"license: {info.get('status')}")
        if info.get("reason"):
            self._print(f"  reason: {info['reason']}")
        if info.get("subscription_status"):
            self._print(f"  subscription: {info['subscription_status']} quota={info.get('quota_remaining')}")
        return True

    def _do_doctor(self) -> bool:
        from ..radius_client import RadiusClient

        from ..license_guard import LicenseGuard

        info = LicenseGuard(self.config).status()
        self._print(f"license: {info.get('status')}")
        with RadiusClient(self.config.radius_url, self.config.radius_token) as r:
            healthy = r.health()
            self._print(f"backend: {'OK' if healthy else 'UNREACHABLE'} at {r.base_url}")
        return True

    def _do_config_show(self) -> bool:
        import dataclasses

        for f in dataclasses.fields(self.config):
            self._print(f"{f.name} = {getattr(self.config, f.name)}")
        return True

    def _do_llm_show(self) -> bool:
        from ..llm import llm_status

        info = llm_status(self.config)
        for k, v in info.items():
            self._print(f"{k} = {v}")
        if info["key_source"] == "MISSING":
            self._print("Run `tia-agent llm set` to store a key.")
        return True

    def _do_analyze(self, repo: str, pr: str) -> bool:
        # Route the command through the LLM-guided flow so it gets step
        # explanations and the instrumentation gate (A3).
        return self._do_converse(f"analyze {repo} pr {pr}")


class _ReplUI:
    """Adapts the REPL's input/output to the ConversationFlow UI protocol."""

    def __init__(self, input_fn, output_fn):
        self._input = input_fn
        self._out = output_fn

    def say(self, message: str) -> None:
        self._out(message)

    def ask(self, prompt: str) -> str:
        try:
            return self._input(prompt)
        except (EOFError, KeyboardInterrupt):
            return ""

    def confirm(self, prompt: str) -> bool:
        try:
            answer = self._input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer in ("y", "yes")


def _interpret(line: str) -> Optional[_Interpreted]:
    if line.startswith("analyze"):
        toks = shlex.split(line)
        if len(toks) >= 3:
            return _Interpreted("analyze", [toks[1], toks[2]])
        # "analyze owner/repo#12"
        m = re.match(r"analyze\s+([\w./-]+)#(\d+)", line)
        if m:
            return _Interpreted("analyze", [m.group(1), m.group(2)])
        return _Interpreted("analyze", [])
    if line.startswith("activate"):
        toks = shlex.split(line)
        if len(toks) >= 2:
            return _Interpreted("activate", [toks[1]])
        return _Interpreted("activate", [])
    return None