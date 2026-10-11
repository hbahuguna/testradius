from tia_agent.interfaces.cli import _build_parser, main
from tia_agent.interfaces.repl import Repl, _interpret


class _FakeInput:
    def __init__(self, lines):
        self._lines = list(lines)

    def __call__(self, prompt):
        if not self._lines:
            raise EOFError
        return self._lines.pop(0)


def test_parser_requires_repo_and_pr():
    p = _build_parser()
    args = p.parse_args(["analyze", "--repo", "owner/repo", "--pr", "3"])
    assert args.command == "analyze"
    assert args.repo == "owner/repo"
    assert args.pr == 3


def test_parser_accepts_repo_path():
    p = _build_parser()
    args = p.parse_args(["analyze", "--repo", "owner/repo", "--pr", "3",
                         "--repo-path", "/tmp/checkout"])
    assert args.repo_path == "/tmp/checkout"


def test_main_version(capsys):
    import sys

    try:
        rc = main(["--version"])
    except SystemExit as e:
        rc = e.code
    assert rc == 0
    assert "tia-agent" in capsys.readouterr().out


def test_main_config_show(capsys):
    rc = main(["config", "show"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "radius_url" in out


def test_repl_exits_on_quit():
    seen = []
    repl = Repl(_cfg(), input_fn=_FakeInput(["quit"]), output_fn=seen.append)
    assert repl.run() == 0
    assert any("tia-agent" in line for line in seen)


def test_repl_help():
    seen = []
    repl = Repl(_cfg(), input_fn=_FakeInput(["help", "quit"]), output_fn=seen.append)
    repl.run()
    assert any("analyze REPO PR" in line for line in seen)


def test_interpreting_analyze():
    parsed = _interpret("analyze owner/repo 12")
    assert parsed is not None
    assert parsed.verb == "analyze"
    assert parsed.args == ["owner/repo", "12"]

    parsed = _interpret("analyze owner/repo#12")
    assert parsed.args == ["owner/repo", "12"]


def test_interpreting_activate():
    parsed = _interpret("activate TIA-ABC-123")
    assert parsed.verb == "activate"
    assert parsed.args == ["TIA-ABC-123"]


def test_interpret_unknown_returns_none():
    assert _interpret("hello there") is None


def _cfg():
    from tia_agent.config import TiaConfig

    return TiaConfig()


# ---------------------------------------------------------------------------
# llm subcommand family
# ---------------------------------------------------------------------------

import pytest


@pytest.fixture()
def _file_creds(tmp_path, monkeypatch):
    monkeypatch.setenv("TIA_CREDENTIALS_BACKEND", "file")
    monkeypatch.setenv("TIA_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("TIA_LLM_PROVIDER", raising=False)
    return tmp_path


def test_cli_llm_set_then_show(_file_creds, capsys):
    rc = main(["llm", "set", "--provider", "openai", "--model", "gpt-4o-mini",
               "--key", "sk-cli-user-key"])
    assert rc == 0
    capsys.readouterr()

    rc = main(["llm", "show"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "openai" in out
    assert "gpt-4o-mini" in out
    assert "file" in out           # key source
    assert "sk-cli-user-key" not in out       # never echoed
    assert "sk-cli-user-key" not in (_file_creds / "config.json").read_text()


def test_cli_llm_show_json(_file_creds, capsys):
    import json as _json

    main(["llm", "set", "--provider", "anthropic", "--key", "ant-cli-key"])
    capsys.readouterr()
    main(["llm", "show", "--json"])
    info = _json.loads(capsys.readouterr().out)
    assert info["provider"] == "anthropic"
    assert info["key_present"] is True
    assert "ant-cli-key" not in _json.dumps(info)


def test_cli_llm_show_before_config(_file_creds, capsys):
    rc = main(["llm", "show"])
    assert rc == 0
    assert "(not configured)" in capsys.readouterr().out


def test_cli_llm_set_ollama_no_key(_file_creds, capsys):
    rc = main(["llm", "set", "--provider", "ollama"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ollama" in out
    assert "llama3.2" in out


def test_cli_llm_unknown_subcommand(_file_creds):
    with pytest.raises(SystemExit) as e:
        main(["llm", "bogus"])
    assert e.value.code == 2


def test_repl_llm_show(_file_creds):
    from tia_agent.config import TiaConfig

    main(["llm", "set", "--provider", "google", "--key", "gem-cli-key"])
    seen = []
    repl = Repl(TiaConfig.load(), input_fn=_FakeInput(["llm", "quit"]),
                output_fn=seen.append)
    repl.run()
    joined = "\n".join(seen)
    assert "google" in joined
    assert "gem-cli-key" not in joined


def test_repl_first_run_onboarding(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TIA_CREDENTIALS_BACKEND", "file")
    monkeypatch.setenv("TIA_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("TIA_SKIP_ONBOARDING", raising=False)

    import tia_agent.interfaces.onboarding as ob
    monkeypatch.setattr(ob, "onboarding_needed", lambda cfg: True)

    from tia_agent.config import TiaConfig

    cfg = TiaConfig()
    repl = Repl(cfg, input_fn=_FakeInput(["1", "gpt-4o-mini", "quit"]),
                output_fn=lambda *_: None, getpass_fn=lambda p: "sk-onboard-key")
    repl.run()
    assert cfg.llm_provider == "openai"
    assert (tmp_path / "config.json").exists()
    assert (tmp_path / "credentials.json").exists()
    assert "sk-onboard-key" not in (tmp_path / "config.json").read_text()


# ---------------------------------------------------------------------------
# A3: REPL routes conversation into the flow
# ---------------------------------------------------------------------------

class _FakeFlow:
    def __init__(self):
        self.handled = []

    def handle(self, text):
        self.handled.append(text)
        return None


def test_repl_routes_free_text_to_flow():
    flow = _FakeFlow()
    seen = []
    repl = Repl(_cfg(), input_fn=_FakeInput(["which tests for acme/shop pr 42", "quit"]),
                output_fn=seen.append, flow_factory=lambda ui: flow)
    repl.run()
    assert flow.handled == ["which tests for acme/shop pr 42"]


def test_repl_analyze_command_goes_through_flow():
    flow = _FakeFlow()
    repl = Repl(_cfg(), input_fn=_FakeInput(["analyze acme/shop 42", "quit"]),
                output_fn=lambda *_: None, flow_factory=lambda ui: flow)
    repl.run()
    assert flow.handled == ["analyze acme/shop pr 42"]


def test_repl_greeting_does_not_trigger_flow():
    flow = _FakeFlow()
    seen = []
    repl = Repl(_cfg(), input_fn=_FakeInput(["hello there", "quit"]),
                output_fn=seen.append, flow_factory=lambda ui: flow)
    repl.run()
    assert flow.handled == []
    assert any("Test Impact Analysis" in line for line in seen)