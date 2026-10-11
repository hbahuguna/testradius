"""A3: LLM-guided conversational flow — intake, gates, evaluation, privacy."""

import json

import pytest

from tia_agent.analyze import AnalyzeRunner
from tia_agent.config import TiaConfig
from tia_agent.conversation import (
    ConversationFlow,
    PrivacyError,
    build_context,
    evaluate,
    parse_slots,
    validate,
)
from tia_agent.conversation.context import assert_d11_safe
from tia_agent.conversation.flow import EXPLAIN_FALLBACK
from tia_agent.conversation.intake import Slots, missing_slots, normalize_repo, question_for
from tia_agent.conversation.toolbox import Evidence
from tia_agent.radius_client import ProjectInfo


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------

def _sample_raw():
    return {
        "project_id": 7,
        "full_name": "acme/shop",
        "pr_number": 42,
        "commit_sha": "abc123",
        "pr_files_analyzed": 2,
        "pr_files": ["src/cart.ts", "src/pricing.ts"],
        "symbols_selected": 2,
        "tests_selected": 1,
        "total_tests_reused": 1,
        "results": [
            {
                "symbol_name": "applyDiscount",
                "existing_tests": [
                    {"test_name": "test_apply_discount", "test_file": "tests/cart.spec.ts"}
                ],
            }
        ],
    }


class _FakeRadius:
    def __init__(self, raw=None):
        self.projects = [ProjectInfo(id=7, name="acme/shop")]
        self.raw = raw if raw is not None else _sample_raw()
        self.base_url = "http://radius:8000"
        self.analyzed = []
        self.instrument_calls = []

    def list_projects(self):
        return self.projects

    def analyze_pr(self, **kwargs):
        self.analyzed.append(kwargs)
        return self.raw

    def run_instrumentation(self, payload):
        self.instrument_calls.append(payload)
        return {"status": "COMPLETED"}


class _FakeGuard:
    def __init__(self, valid=True):
        self.valid = valid
        self.recorded = []

    def ensure_valid(self):
        if not self.valid:
            from tia_agent.errors import LicenseError

            raise LicenseError("License expired beyond grace")

    def record_run(self, run_id, repo_hash, metadata):
        self.recorded.append((run_id, repo_hash, metadata))


class UI:
    """Scripted UI: answers/confirmations consumed in order."""

    def __init__(self, answers=(), confirms=()):
        self.said = []
        self.asked = []
        self.confirmations = []
        self._answers = list(answers)
        self._confirms = list(confirms)

    def say(self, message):
        self.said.append(message)

    def ask(self, prompt):
        self.asked.append(prompt)
        return self._answers.pop(0) if self._answers else ""

    def confirm(self, prompt):
        self.confirmations.append(prompt)
        return self._confirms.pop(0) if self._confirms else False

    @property
    def transcript(self):
        return "\n".join(self.said)


class FakeToolbox:
    def __init__(self, evidence):
        self.evidence = evidence
        self.instrumented = []
        self.check_calls = []

    def check_evidence(self, repo, project, file_paths=None):
        self.check_calls.append((repo, file_paths))
        return self.evidence

    def run_instrumentation(self, repo, project, file_paths=None):
        self.instrumented.append(repo)
        return {"status": "COMPLETED"}


def _flow(ui, toolbox, llm=None, guard=None):
    config = TiaConfig()
    radius = _FakeRadius()
    guard = guard or _FakeGuard()
    runner = AnalyzeRunner(config, guard, radius)
    flow = ConversationFlow(config, runner, ui, toolbox=toolbox, llm=llm)
    return flow, runner, radius, guard


FRESH = Evidence(known=True, fresh=True, reason="evidence is fresh")
STALE = Evidence(known=True, fresh=False, reason="evidence is stale")
UNKNOWN = Evidence(known=False, fresh=False, reason="no checker")


# ---------------------------------------------------------------------------
# intake
# ---------------------------------------------------------------------------

def test_parse_repo_and_pr_from_text():
    s = parse_slots("analyze acme/shop pr 42")
    assert s.repo == "acme/shop"
    assert s.pr_number == 42


def test_parse_github_url():
    s = parse_slots("run TIA on https://github.com/acme/shop/pull/42")
    assert s.repo == "acme/shop"
    assert s.pr_number == 42


def test_parse_hash_reference():
    s = parse_slots("check #17 for acme/shop")
    assert (s.repo, s.pr_number) == ("acme/shop", 17)


def test_normalize_repo_strips_git_and_url():
    assert normalize_repo("https://github.com/acme/shop.git") == "acme/shop"
    assert normalize_repo("acme/shop/") == "acme/shop"


def test_missing_slots_and_questions():
    s = Slots()
    assert missing_slots(s) == ["repo", "pr_number"]
    assert "repository" in question_for("repo").lower()
    assert "pr" in question_for("pr_number").lower()


def test_validate_reports_problems():
    assert validate(Slots(repo="", pr_number=None))
    assert validate(Slots(repo="not-a-repo", pr_number=5))
    assert validate(Slots(repo="acme/shop", pr_number=-1))
    assert validate(Slots(repo="acme/shop", pr_number=5)) == []


def test_llm_assisted_extraction_for_natural_language():
    replies = iter(['Sure! {"repo": "acme/shop", "pr_number": 42}'])

    def llm(_messages):
        return next(replies)

    s = parse_slots("can you look into the discount change please", llm=llm)
    assert (s.repo, s.pr_number) == ("acme/shop", 42)


def test_llm_failure_does_not_break_parsing():
    def boom(_messages):
        raise RuntimeError("provider down")

    s = parse_slots("acme/shop #7", llm=boom)
    assert (s.repo, s.pr_number) == ("acme/shop", 7)


# ---------------------------------------------------------------------------
# AC: agent asks for missing inputs
# ---------------------------------------------------------------------------

def test_flow_asks_for_missing_repo_and_pr():
    ui = UI(answers=["acme/shop", "42"], confirms=[True])
    flow, runner, radius, guard = _flow(ui, FakeToolbox(FRESH))
    res = flow.handle("analyze something")

    assert res.status == "ok"
    assert len(ui.asked) == 2                       # repo, then pr
    assert "repository" in ui.asked[0].lower()
    assert "pr" in ui.asked[1].lower()
    assert radius.analyzed[0]["full_name"] == "acme/shop"
    assert radius.analyzed[0]["pr_number"] == 42


def test_flow_only_asks_for_what_is_missing():
    ui = UI(answers=["42"], confirms=[True])
    flow, *_ = _flow(ui, FakeToolbox(FRESH))
    flow.handle("analyze the change in acme/shop")   # repo present, pr missing
    assert len(ui.asked) == 1
    assert "pr" in ui.asked[0].lower()


def test_flow_cancels_when_intake_gets_no_answer():
    ui = UI(answers=[""])                             # user gives up
    flow, runner, radius, guard = _flow(ui, FakeToolbox(FRESH))
    res = flow.handle("analyze something")
    assert res.status == "cancelled"
    assert radius.analyzed == []


# ---------------------------------------------------------------------------
# AC: agent asks before instrumentation (D10)
# ---------------------------------------------------------------------------

def test_instrumentation_is_not_run_when_user_declines():
    ui = UI(answers=[], confirms=[True, False])       # run=yes, instrument=no
    toolbox = FakeToolbox(STALE)
    flow, *_ = _flow(ui, toolbox)
    res = flow.handle("analyze acme/shop pr 42")
    assert res.status == "ok"
    assert res.instrumented is False
    assert toolbox.instrumented == []
    assert any("instrumentation" in c.lower() for c in ui.confirmations)
    assert "Skipping instrumentation" in ui.transcript


def test_instrumentation_runs_only_after_explicit_approval():
    ui = UI(answers=[], confirms=[True, True])
    toolbox = FakeToolbox(STALE)
    flow, *_ = _flow(ui, toolbox)
    res = flow.handle("analyze acme/shop pr 42")
    assert res.instrumented is True
    assert toolbox.instrumented == ["acme/shop"]
    assert any("instrumentation" in c.lower() for c in ui.confirmations)


def test_fresh_evidence_skips_instrumentation_entirely():
    ui = UI(answers=[], confirms=[True])              # only the run gate
    toolbox = FakeToolbox(FRESH)
    flow, *_ = _flow(ui, toolbox)
    flow.handle("analyze acme/shop pr 42")
    assert toolbox.instrumented == []
    assert len(ui.confirmations) == 1                 # no instrumentation prompt


def test_unknown_evidence_still_asks_rather_than_auto_running():
    ui = UI(answers=[], confirms=[True, False])
    toolbox = FakeToolbox(UNKNOWN)
    flow, *_ = _flow(ui, toolbox)
    flow.handle("analyze acme/shop pr 42")
    assert toolbox.instrumented == []                 # never auto-runs
    assert len(ui.confirmations) == 2


# ---------------------------------------------------------------------------
# run confirmation + metering
# ---------------------------------------------------------------------------

def test_declining_the_run_does_not_analyze_or_meter():
    ui = UI(answers=[], confirms=[False])
    flow, runner, radius, guard = _flow(ui, FakeToolbox(FRESH))
    res = flow.handle("analyze acme/shop pr 42")
    assert res.status == "cancelled"
    assert radius.analyzed == []
    assert guard.recorded == []


def test_successful_flow_meters_once():
    ui = UI(answers=[], confirms=[True])
    flow, runner, radius, guard = _flow(ui, FakeToolbox(FRESH))
    res = flow.handle("analyze acme/shop pr 42")
    assert res.status == "ok"
    assert len(guard.recorded) == 1


# ---------------------------------------------------------------------------
# step explanations
# ---------------------------------------------------------------------------

def test_deterministic_explanations_when_no_llm():
    ui = UI(answers=[], confirms=[True])
    flow, *_ = _flow(ui, FakeToolbox(FRESH), llm=None)
    flow.handle("analyze acme/shop pr 42")
    t = ui.transcript
    for step in ("license", "project", "evidence", "analyze", "meter"):
        assert EXPLAIN_FALLBACK[step] in t


def test_llm_explanations_are_used_when_available():
    calls = []

    def llm(messages):
        calls.append(messages)
        if "JSON only" in messages[-1]["content"]:
            return "{}"
        return "LLM-EXPLANATION"

    ui = UI(answers=[], confirms=[True])
    flow, *_ = _flow(ui, FakeToolbox(FRESH), llm=llm)
    flow.handle("analyze acme/shop pr 42")
    assert "LLM-EXPLANATION" in ui.transcript
    assert calls  # llm was actually consulted


# ---------------------------------------------------------------------------
# result evaluation
# ---------------------------------------------------------------------------

def _result(**overrides):
    from tia_agent.analyze import TiaResult

    base = dict(
        tia_run_id="r1", repo="acme/shop", pr_number=42,
        files_analyzed=2, symbols_selected=2, tests_selected=1,
        total_affected_tests=1, total_tests_in_repo=None,
        fallback_used=False, fallback_reason=None, confidence="high",
        tests=[{"file": "tests/cart.spec.ts", "name": "test_apply_discount",
                "nodeid": "tests/cart.spec.ts::test_apply_discount",
                "language": "typescript", "reason": "applyDiscount"}],
        run_commands=["npx playwright test tests/cart.spec.ts"],
    )
    base.update(overrides)
    return TiaResult(**base)


def test_evaluate_high_confidence_summary_and_actions():
    ev = evaluate(_result())
    assert ev.confidence == "high"
    assert ev.fallback_used is False
    assert ev.safety_flag is False
    assert "1 affected test" in ev.summary
    assert "npx playwright test tests/cart.spec.ts" in ev.next_actions


def test_evaluate_flags_safety_above_30_percent():
    ev = evaluate(_result(total_affected_tests=8, total_tests_in_repo=10))
    assert ev.safety_flag is True
    assert ev.impacted_ratio == 0.8
    assert any("full suite" in a for a in ev.next_actions)


def test_evaluate_fallback_recommends_full_suite():
    ev = evaluate(_result(
        symbols_selected=0, tests_selected=0, total_affected_tests=0,
        fallback_used=True, fallback_reason="no reusable mappings",
        confidence="low", tests=[], run_commands=[],
    ))
    assert ev.fallback_used is True
    assert "no reusable mappings" in ev.summary
    assert any("full test suite" in a for a in ev.next_actions)


def test_evaluate_llm_phrases_summary(tmp_path):
    def llm(_messages):
        return "Everything looks good; 1 test to run."

    ev = evaluate(_result(), llm=llm)
    assert ev.summary == "Everything looks good; 1 test to run."


def test_evaluate_survives_llm_failure():
    def boom(_messages):
        raise RuntimeError("nope")

    ev = evaluate(_result(), llm=boom)
    assert "1 affected test" in ev.summary


# ---------------------------------------------------------------------------
# D11 privacy
# ---------------------------------------------------------------------------

def test_build_context_contains_only_allowed_keys():
    ctx = build_context(repo="acme/shop", pr_number=42, raw=_sample_raw())
    from tia_agent.conversation.context import ALLOWED_KEYS

    assert set(ctx) <= ALLOWED_KEYS
    assert ctx["changed_files"] == ["src/cart.ts", "src/pricing.ts"]
    assert ctx["symbols"] == ["applyDiscount"]


def test_build_context_excludes_test_names_and_code():
    ctx = build_context(repo="acme/shop", pr_number=42, raw=_sample_raw())
    blob = json.dumps(ctx)
    assert "test_apply_discount" not in blob        # test name not sent
    assert "def " not in blob


def test_assert_d11_safe_rejects_forbidden_and_unknown_fields():
    with pytest.raises(PrivacyError):
        assert_d11_safe({"code": "print('hi')"})
    with pytest.raises(PrivacyError):
        assert_d11_safe({"totally_new_field": 1})
    with pytest.raises(PrivacyError):
        assert_d11_safe({"changed_files": ["line1\nline2"]})


def test_llm_never_receives_test_names_or_code():
    captured = []

    def llm(messages):
        captured.append(json.dumps(messages))
        if "JSON only" in messages[-1]["content"]:
            return "{}"
        return "ok"

    ui = UI(answers=[], confirms=[True])
    flow, *_ = _flow(ui, FakeToolbox(FRESH), llm=llm)
    flow.handle("analyze acme/shop pr 42")

    blob = "\n".join(captured)
    assert "test_apply_discount" not in blob        # no test names to the LLM
    assert "applyDiscount" in blob                  # symbol names are allowed
    assert "src/cart.ts" in blob                    # changed paths are allowed
    assert "def " not in blob                        # no source code