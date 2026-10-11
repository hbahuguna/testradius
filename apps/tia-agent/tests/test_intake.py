"""E3/T3: PR-file intake wired into the flow and the `intake` CLI command."""

import json

import pytest

from tia_agent.analyze import AnalyzeRunner
from tia_agent.config import TiaConfig
from tia_agent.conversation import ConversationFlow
from tia_agent.conversation.toolbox import Evidence
from tia_agent.errors import GitHubAuthError, GitHubError
from tia_agent.interfaces.cli import main
from tia_agent.radius_client import ProjectInfo
from tia_agent.tools.github import PrFile


RAW = {
    "pr_files_analyzed": 1,
    "symbols_selected": 1,
    "tests_selected": 1,
    "total_tests_reused": 1,
    "results": [
        {"symbol_name": "a", "existing_tests": [{"test_name": "t", "test_file": "tests/a.spec.ts"}]}
    ],
}


class _FakeRadius:
    base_url = "http://radius:8000"

    def __init__(self):
        self.analyzed = []

    def list_projects(self):
        return [ProjectInfo(id=1, name="acme/shop")]

    def analyze_pr(self, **kwargs):
        self.analyzed.append(kwargs)
        return RAW


class _FakeGuard:
    def ensure_valid(self):
        pass

    def record_run(self, run_id, repo_hash, metadata):
        pass


class UI:
    def __init__(self, answers=(), confirms=(True,)):
        self.said = []
        self.asked = []
        self._answers = list(answers)
        self._confirms = list(confirms)

    def say(self, message):
        self.said.append(message)

    def ask(self, prompt):
        self.asked.append(prompt)
        return self._answers.pop(0) if self._answers else ""

    def confirm(self, prompt):
        return self._confirms.pop(0) if self._confirms else False

    @property
    def transcript(self):
        return "\n".join(self.said)


class _FakeToolbox:
    def __init__(self, evidence):
        self.evidence = evidence

    def check_evidence(self, repo, project, file_paths=None):
        return self.evidence

    def run_instrumentation(self, repo, project, file_paths=None):
        return {"status": "COMPLETED"}


FRESH = Evidence(known=True, fresh=True, reason="fresh")


def _github_factory(*, require_token=False, raise_error=False):
    class _FakeGitHub:
        def __init__(self, token="", *a, **k):
            self.token = token

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def get_pr_files(self, full_name, pr_number):
            if raise_error:
                raise GitHubError("boom")
            if require_token and self.token != "good":
                raise GitHubAuthError("401")
            return [PrFile("tests/a.spec.ts"), PrFile("src/a.ts"), PrFile("README.md")]

    return _FakeGitHub


def _flow(ui, *, require_token=False, raise_error=False, token_prompt=None, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setattr(
            "tia_agent.analyze.GitHubClient",
            _github_factory(require_token=require_token, raise_error=raise_error),
        )
    config = TiaConfig()
    radius = _FakeRadius()
    runner = AnalyzeRunner(config, _FakeGuard(), radius)
    flow = ConversationFlow(
        config, runner, ui, toolbox=_FakeToolbox(FRESH),
        token_prompt=token_prompt,
    )
    return flow, radius


def test_flow_fetches_pr_files(monkeypatch):
    ui = UI()
    flow, radius = _flow(ui, monkeypatch=monkeypatch)
    result = flow.handle("analyze acme/shop pr 42")
    assert result.status == "ok"
    assert radius.analyzed[-1]["file_paths"] == ["tests/a.spec.ts", "src/a.ts"]


def test_flow_prompts_for_token_and_retries(monkeypatch):
    ui = UI()
    prompts = []

    def token_prompt():
        prompts.append(True)
        return "good"

    flow, radius = _flow(ui, require_token=True, token_prompt=token_prompt, monkeypatch=monkeypatch)
    result = flow.handle("analyze acme/shop pr 42")
    assert result.status == "ok"
    assert prompts == [True]
    assert radius.analyzed[-1]["file_paths"] == ["tests/a.spec.ts", "src/a.ts"]


def test_flow_continues_without_token_when_no_prompt(monkeypatch):
    ui = UI()
    flow, radius = _flow(ui, require_token=True, token_prompt=None, monkeypatch=monkeypatch)
    result = flow.handle("analyze acme/shop pr 42")
    assert result.status == "ok"
    assert radius.analyzed[-1]["file_paths"] is None
    assert "continuing" in ui.transcript.lower()


def test_flow_continues_on_github_error(monkeypatch):
    ui = UI()
    flow, radius = _flow(ui, raise_error=True, token_prompt=lambda: "x", monkeypatch=monkeypatch)
    result = flow.handle("analyze acme/shop pr 42")
    assert result.status == "ok"
    assert radius.analyzed[-1]["file_paths"] is None


def test_cli_intake_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TIA_CREDENTIALS_BACKEND", "file")
    monkeypatch.setenv("TIA_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("TIA_GITHUB_TOKEN", raising=False)
    monkeypatch.setattr("tia_agent.tools.github.GitHubClient", _github_factory())

    rc = main(["intake", "--repo", "acme/shop", "--pr", "42", "--no-prompt", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["repo"] == "acme/shop"
    assert payload["pr_number"] == 42
    assert payload["files"] == ["tests/a.spec.ts", "src/a.ts"]
    assert payload["language"] == "playwright"  # a.spec.ts dominates
    assert payload["instrumentation_language"] == "playwright"
