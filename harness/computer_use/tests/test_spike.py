import json
from pathlib import Path

from harness.computer_use.gemini_client import MockGeminiComputerUseClient, ProposedAction
from harness.computer_use.primitives import MockComputerUsePrimitives
from harness.computer_use.spike import ActionValidator, ComputerUseSpikeRunner
from harness.testplan import CompiledExecutionTestPlan

TINY = Path(__file__).resolve().parents[3] / "evals" / "fixtures" / "computer_use_tiny_plan.json"


def load_tiny() -> dict:
    return json.loads(TINY.read_text())


def test_tiny_plan_passes_local_spike_gate():
    from harness.testplan import CompiledPlanValidator
    plan = CompiledExecutionTestPlan.model_validate(load_tiny())
    result = CompiledPlanValidator().validate(plan, mode="local_spike")
    assert result.ok, result.to_dict()


def test_spike_runner_executes_tiny_plan_with_mocks(tmp_path: Path):
    primitives = MockComputerUsePrimitives()
    client = MockGeminiComputerUseClient(script=[
        {"action_type": "navigate", "url": "https://testradius.dev/", "reason": "Open homepage"},
        {"action_type": "assert", "reason": "Hero visible"},
    ])
    runner = ComputerUseSpikeRunner(primitives=primitives, gemini_client=client, artifacts_dir=tmp_path)
    report = runner.run(run_id="run-tiny", plan=load_tiny())
    assert report.status == "COMPLETED"
    assert len(report.steps) == 2
    assert all(s.status == "PASSED" for s in report.steps)
    assert (tmp_path / "run-tiny" / "spike_report.json").exists()
    assert (tmp_path / "run-tiny" / "compiled_test_plan.json").exists()
    assert primitives.current_url == "https://testradius.dev/"
    assert len(client.calls) == 2


def test_action_validator_blocks_out_of_domain_navigate(tmp_path: Path):
    plan = CompiledExecutionTestPlan.model_validate(load_tiny())
    validator = ActionValidator(plan)
    step = plan.cases[0].steps[0]
    bad = ProposedAction({"action_type": "navigate", "url": "https://evil.example.com/", "reason": "bad"})
    check = validator.validate(step, bad)
    assert not check["ok"]
    assert any("not in allowed_domains" in e for e in check["errors"])


def test_action_validator_blocks_out_of_bounds_click(tmp_path: Path):
    plan = CompiledExecutionTestPlan.model_validate(load_tiny())
    step = plan.cases[0].steps[0]
    click_step = step.model_copy(update={"step_id": "X", "action_type": "click", "intent": "Click CTA", "success_criteria": ["CTA clickable"], "fallback_instructions": ["scroll"]})
    validator = ActionValidator(plan)
    bad = ProposedAction({"action_type": "click", "x": 9999, "y": 10, "reason": "bad bounds"})
    check = validator.validate(click_step, bad)
    assert not check["ok"]
    assert any("out of bounds" in e for e in check["errors"])


def test_spike_runner_blocks_invalid_proposal_with_evidence(tmp_path: Path):
    primitives = MockComputerUsePrimitives()
    client = MockGeminiComputerUseClient(script=[
        {"action_type": "navigate", "url": "https://evil.example.com/", "reason": "bad domain"},
        {"action_type": "assert", "reason": "ok"},
    ])
    runner = ComputerUseSpikeRunner(primitives=primitives, gemini_client=client, artifacts_dir=tmp_path)
    report = runner.run(run_id="run-blocked", plan=load_tiny())
    assert report.status == "BLOCKED"
    assert report.steps[0].status == "BLOCKED"
    assert report.steps[1].status == "PASSED"
