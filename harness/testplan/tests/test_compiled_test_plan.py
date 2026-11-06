import json
from copy import deepcopy
from pathlib import Path

import pytest

from harness.testplan import CompiledExecutionTestPlan, CompiledPlanValidator

FIXTURE = Path(__file__).resolve().parents[3] / "evals" / "fixtures" / "compiled_test_plan.valid.json"


def load_valid() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_golden_valid_plan_parses_and_passes_validation():
    data = load_valid()
    plan = CompiledExecutionTestPlan.model_validate(data)
    assert plan.plan_id == "ctp-golden-homepage-001"
    assert plan.sut.base_url.startswith("https://")
    result = CompiledPlanValidator().validate(plan, mode="local_spike")
    assert result.ok, result.to_dict()
    assert result.errors == []


def test_validator_rejects_missing_target_preconditions_cases_and_allowed_domains():
    data = load_valid()
    data["sut"]["base_url"] = ""
    data["preconditions"] = []
    data["cases"] = []
    data["constraints"]["allowed_domains"] = []
    result = CompiledPlanValidator().validate(data, mode="local_spike")
    codes = {i.code for i in result.errors}
    assert "missing_target" in codes or "invalid_target" in codes
    assert "missing_preconditions" in codes
    assert "missing_cases" in codes
    assert "missing_allowed_domains" in codes


def test_validator_rejects_missing_step_success_criteria_evidence_and_vague_assertions():
    data = load_valid()
    step = data["cases"][0]["steps"][0]
    step["success_criteria"] = ["verify it works"]
    step["evidence"] = {
        "screenshot_before": False,
        "screenshot_after": False,
        "screenshot_on_failure": False,
        "dom_text": False,
        "action_trace": False,
    }
    result = CompiledPlanValidator().validate(data, mode="local_spike")
    codes = {i.code for i in result.errors}
    assert "vague_success_criteria" in codes
    assert "missing_evidence" in codes


def test_validator_rejects_inline_secrets_and_secret_value_refs():
    data = load_valid()
    data["cases"][0]["steps"][1]["input"] = {"password": "hunter2-super-secret"}
    data["sut"]["auth_secret_refs"] = {"password": "sk-live-THIS_IS_A_SECRET_VALUE_NOT_A_NAME"}
    result = CompiledPlanValidator().validate(data, mode="local_spike")
    codes = {i.code for i in result.errors}
    assert "inline_secret" in codes


def test_validator_allows_env_and_test_data_refs():
    data = load_valid()
    data["cases"][0]["steps"][1]["input"] = "{{env.TEST_USER_EMAIL}}"
    data["sut"]["auth_mode"] = "test_account_ref"
    data["sut"]["auth_secret_refs"] = {"password": "TEST_USER_PASSWORD"}
    result = CompiledPlanValidator().validate(data, mode="local_spike")
    assert not any(i.code == "inline_secret" for i in result.errors)


def test_production_requires_human_approved_review_status():
    data = load_valid()
    data["quality_gate"]["review_status"] = "draft"
    result = CompiledPlanValidator().validate(data, mode="production", require_human_review_for_production=True)
    assert any(i.code == "review_not_approved" for i in result.errors)
    result_local = CompiledPlanValidator().validate(data, mode="local_spike")
    assert not any(i.code == "review_not_approved" for i in result_local.errors)
    assert any(w.code == "draft_plan" for w in result_local.warnings)


def test_target_must_be_covered_by_allowed_domains():
    data = load_valid()
    data["constraints"]["allowed_domains"] = ["example.com"]
    result = CompiledPlanValidator().validate(data, mode="local_spike")
    assert any(i.code == "target_not_allowed" for i in result.errors)


def test_ac_coverage_warns_when_provided_acs_not_covered():
    data = load_valid()
    result = CompiledPlanValidator().validate(
        data,
        mode="local_spike",
        provided_acs=["User can export billing invoices as encrypted PDF"],
    )
    assert result.ok  # warning-level coverage gap by default
    assert any(w.code == "ac_coverage_gap" for w in result.warnings)


def test_destructive_step_requires_human_approval():
    data = load_valid()
    step = deepcopy(data["cases"][0]["steps"][0])
    step.update({"step_id": "C1-S9", "ordinal": 9, "intent": "Delete test account", "action_type": "click", "destructive": True, "requires_human_approval": False})
    data["cases"][0]["steps"].append(step)
    result = CompiledPlanValidator().validate(data, mode="local_spike")
    assert any(i.code == "destructive_requires_approval" for i in result.errors)
