"""E5/P1: outbound payload privacy — LLM fields (D11) and license metadata (D12).

These tests assert against the *actual outbound payloads*, not just the
allowlist constants: the LLM messages built by the flow and the metadata handed
to the license client.
"""

import json
import re
from pathlib import Path

import pytest

from tia_agent.analyze import AnalyzeRunner
from tia_agent.config import TiaConfig
from tia_agent.conversation import (
    ConversationFlow,
    PrivacyError,
    build_context,
)
from tia_agent.conversation.context import ALLOWED_KEYS, assert_d11_safe
from tia_agent.conversation.prompts import (
    evaluate_messages,
    explain_messages,
    slots_messages,
)
from tia_agent.conversation.toolbox import Evidence
from tia_agent.license_guard import LicenseGuard
from tia_agent.privacy import (
    LICENSE_METADATA_ALLOWED,
    LLM_CONTEXT_ALLOWED,
    assert_license_metadata_safe,
    assert_llm_context_safe,
    filter_license_metadata,
)
from tia_agent.radius_client import ProjectInfo

REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY_DOC = REPO_ROOT / "docs" / "project" / "tia-commercial-agent" / "PRIVACY.md"
SERVER_SERVICE = REPO_ROOT / "services" / "license" / "license_server" / "service.py"

# Strings that must never reach an external service (code / test content).
POISON = (
    "SECRET_BODY",
    "SECRET_TEST_BODY",
    "price * 0.9",
    "def applyDiscount",
    "function applyDiscount",
    "test_apply_discount",
)


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------

def _poison_raw():
    """A backend response stuffed with fields that must never be forwarded."""
    return {
        "project_id": 7,
        "full_name": "acme/shop",
        "pr_number": 42,
        "commit_sha": "abc123",
        "pr_files_analyzed": 1,
        "pr_files": ["src/cart.ts"],
        "symbols_selected": 1,
        "tests_selected": 1,
        "total_tests_reused": 1,
        "results": [
            {
                "symbol_name": "applyDiscount",
                "source": "def applyDiscount(): return price * 0.9",   # poison
                "body": "SECRET_BODY",
                "diff": "-old\n+new",
                "existing_tests": [
                    {
                        "test_name": "test_apply_discount",
                        "test_file": "tests/cart.spec.ts",
                        "content": "function applyDiscount() { /* SECRET_TEST_BODY */ }",
                    }
                ],
            }
        ],
    }


class _FakeRadius:
    base_url = "http://radius:8000"

    def __init__(self, raw):
        self.raw = raw

    def list_projects(self):
        return [ProjectInfo(id=7, name="acme/shop")]

    def analyze_pr(self, **kwargs):
        return self.raw

    def run_instrumentation(self, payload):
        return {"status": "COMPLETED"}


class _FakeGuard:
    def ensure_valid(self):
        pass

    def record_run(self, *a, **k):
        pass


class _UI:
    def __init__(self, answers=(), confirms=()):
        self.said = []
        self._answers = list(answers)
        self._confirms = list(confirms)

    def say(self, message):
        self.said.append(message)

    def ask(self, prompt):
        return self._answers.pop(0) if self._answers else ""

    def confirm(self, prompt):
        return self._confirms.pop(0) if self._confirms else False


class _FakeToolbox:
    def __init__(self, evidence):
        self.evidence = evidence

    def check_evidence(self, repo, project, file_paths=None):
        return self.evidence

    def run_instrumentation(self, repo, project, file_paths=None):
        return {"status": "COMPLETED"}


FRESH = Evidence(known=True, fresh=True, reason="evidence is fresh for these files")


class _CapturingLicenseClient:
    def __init__(self):
        self.calls = []

    def record_run(self, run_id, metadata):
        self.calls.append((run_id, metadata))
        return None


# ---------------------------------------------------------------------------
# the allowlists are the enforced ones
# ---------------------------------------------------------------------------

def test_context_allowlist_single_sourced_from_privacy():
    assert ALLOWED_KEYS is LLM_CONTEXT_ALLOWED


def test_license_allowlist_matches_license_server():
    """Client and server allowlists must not drift (defense in depth)."""
    text = SERVER_SERVICE.read_text()
    block = re.search(r"def _metadata_allowlist.*?allowed = \{(.*?)\}", text, re.S)
    assert block, "could not find server _metadata_allowlist"
    server_fields = set(re.findall(r'"([a-z_]+)"', block.group(1)))
    assert server_fields == set(LICENSE_METADATA_ALLOWED)


# ---------------------------------------------------------------------------
# LLM context (D11)
# ---------------------------------------------------------------------------

def test_build_context_strips_backend_code_and_test_names():
    ctx = build_context(repo="acme/shop", pr_number=42, raw=_poison_raw())
    assert set(ctx) <= LLM_CONTEXT_ALLOWED
    assert ctx["symbols"] == ["applyDiscount"]        # symbol name only
    assert ctx["changed_files"] == ["src/cart.ts"]    # path only
    blob = json.dumps(ctx)
    for bad in POISON:
        assert bad not in blob, f"{bad!r} leaked into LLM context"
    assert "applyDiscount" in blob


def test_prompt_builders_reject_non_d11_context():
    for builder in (
        lambda ctx: explain_messages("analyze", ctx),
        lambda ctx: evaluate_messages(ctx),
    ):
        with pytest.raises(PrivacyError):
            builder({"code": "def f(): pass"})          # forbidden key
        with pytest.raises(PrivacyError):
            builder({"diff": "..."})                    # forbidden key
        with pytest.raises(PrivacyError):
            builder({"totally_new_field": 1})           # unknown key
        with pytest.raises(PrivacyError):
            builder({"changed_files": ["a\nb"]})        # multiline looks like code


def test_slots_messages_only_embed_known_slots():
    msgs = slots_messages("do the thing", {"repo": "acme/shop", "pr_number": 42,
                                           "commit_sha": "main", "code": "SECRET_BODY"})
    content = msgs[-1]["content"]
    assert "SECRET_BODY" not in content
    assert 'Already known: {"repo": "acme/shop", "pr_number": 42, "commit_sha": "main"}' in content


def test_flow_outbound_llm_payload_is_code_free(monkeypatch):
    import importlib

    # NB: import by module path — ``tia_agent.conversation.evaluate`` is shadowed
    # by the re-exported ``evaluate`` function in the package __init__.
    evaluate_mod = importlib.import_module("tia_agent.conversation.evaluate")
    flow_mod = importlib.import_module("tia_agent.conversation.flow")

    sent_messages = []
    seen_contexts = []

    def capturing_llm(messages):
        sent_messages.append(messages)
        return ""  # force deterministic fallbacks; we only care about the payload

    orig_explain = flow_mod.explain_messages

    def spy_explain(step, context):
        seen_contexts.append(dict(context))
        assert_d11_safe(context)
        return orig_explain(step, context)

    orig_eval = evaluate_mod.evaluate_messages

    def spy_eval(context):
        seen_contexts.append(dict(context))
        assert_d11_safe(context)
        return orig_eval(context)

    monkeypatch.setattr(flow_mod, "explain_messages", spy_explain)
    monkeypatch.setattr(evaluate_mod, "evaluate_messages", spy_eval)

    runner = AnalyzeRunner(TiaConfig(), _FakeGuard(), _FakeRadius(_poison_raw()))
    flow = ConversationFlow(TiaConfig(), runner, _UI(confirms=[True]),
                            toolbox=_FakeToolbox(FRESH), llm=capturing_llm)
    flow.handle("analyze acme/shop pr 42")

    # Every explain/evaluate context handed to a prompt must be D11-safe.
    assert seen_contexts
    for ctx in seen_contexts:
        assert set(ctx) <= LLM_CONTEXT_ALLOWED
        assert_llm_context_safe(ctx)

    # Every message actually sent to the LLM must be free of code/test content.
    assert sent_messages
    blob = json.dumps(sent_messages)
    for bad in POISON:
        assert bad not in blob, f"{bad!r} leaked to the LLM"
    assert "applyDiscount" in blob       # symbol names are allowed
    assert "src/cart.ts" in blob         # changed paths are allowed


# ---------------------------------------------------------------------------
# license metadata (D12)
# ---------------------------------------------------------------------------

def test_filter_license_metadata_strips_unknown_fields():
    filtered = filter_license_metadata({
        "repo_hash": "h", "file_count": 2, "test_count": 3,
        "code": "SECRET_BODY", "changed_files": ["src/cart.ts"],
        "tests": [{"name": "test_apply_discount"}], "symbols": ["applyDiscount"],
    })
    assert filtered == {"repo_hash": "h", "file_count": 2, "test_count": 3}
    assert set(filtered) <= LICENSE_METADATA_ALLOWED


def test_assert_license_metadata_safe_raises_on_extra_field():
    assert_license_metadata_safe({"repo_hash": "h", "file_count": 1})
    with pytest.raises(PrivacyError):
        assert_license_metadata_safe({"repo_hash": "h", "code": "x"})


def test_license_guard_outbound_payload_is_metadata_only():
    guard = LicenseGuard(TiaConfig())
    client = _CapturingLicenseClient()
    guard._client = client

    guard.record_run(
        run_id="run-1",
        repo_hash="deadbeef",
        metadata={
            "file_count": 2,
            "test_count": 3,
            "language": "typescript",
            # injected content that must be stripped before egress:
            "code": "def applyDiscount(): return price * 0.9",
            "changed_files": ["src/cart.ts"],
            "test_names": ["test_apply_discount"],
        },
    )

    assert len(client.calls) == 1
    _run_id, sent = client.calls[0]
    assert set(sent) <= LICENSE_METADATA_ALLOWED
    assert sent["repo_hash"] == "deadbeef"
    blob = json.dumps(sent)
    for bad in POISON:
        assert bad not in blob, f"{bad!r} leaked to the license server"
    assert "src/cart.ts" not in blob     # repo paths never leave


# ---------------------------------------------------------------------------
# written policy
# ---------------------------------------------------------------------------

def test_written_policy_exists_and_documents_both_flows():
    text = POLICY_DOC.read_text()
    assert "D11" in text and "D12" in text
    for field in ("repo_hash", "changed_files", "symbols", "file_count", "test_count"):
        assert field in text
    assert "Never" in text or "never" in text
