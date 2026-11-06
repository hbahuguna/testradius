import json
from pathlib import Path

from harness.computer_use.gemini_client import MockGeminiComputerUseClient
from harness.computer_use.primitives import MockComputerUsePrimitives
from harness.computer_use.ref_resolver import resolve_value
from harness.computer_use.runner import ComputerUseRunner

GOLDEN = Path(__file__).resolve().parents[3] / "evals" / "fixtures" / "compiled_test_plan.valid.json"


def load_golden() -> dict:
    return json.loads(GOLDEN.read_text())


def test_runner_runs_golden_plan_per_step_with_evidence(tmp_path: Path):
    primitives = MockComputerUsePrimitives()
    client = MockGeminiComputerUseClient(script=[
        {"action_type": "navigate", "url": "https://testradius.dev/", "reason": "Open homepage"},
        {"action_type": "assert", "reason": "CTA visible"},
        {"action_type": "click", "x": 720, "y": 420, "reason": "Click CTA"},
    ])
    runner = ComputerUseRunner(primitives=primitives, gemini_client=client, artifacts_dir=tmp_path, mode="local_spike")
    summary = runner.run(run_id="run-golden", plan=load_golden())
    assert summary.status in {"COMPLETED", "BLOCKED", "FAILED"}
    assert summary.total_steps > 0
    # Evidence always produced
    for name in ("action_trace.jsonl", "step_results.json", "run_summary.json", "compiled_test_plan.json"):
        assert (tmp_path / "run-golden" / name).exists(), name
    trace = (tmp_path / "run-golden" / "action_trace.jsonl").read_text().strip().splitlines()
    assert len(trace) >= 1
    # No raw context payload in sandbox trace: trace keys are step-scoped contracts only
    assert all("source_refs" not in line for line in trace)


def test_ref_resolution_env_and_test_data():
    resolved, blocked = resolve_value("{{test_data.expected_cta_text}}", test_data={"expected_cta_text": "Get Started"}, env={})
    assert (resolved, blocked) == ("Get Started", False)
    resolved, blocked = resolve_value("{{env.FOO_BAR}}", test_data={}, env={"FOO_BAR": "baz"})
    assert (resolved, blocked) == ("baz", False)
    resolved, blocked = resolve_value("{{secret.MY_PASSWORD}}", test_data={}, env={})
    assert blocked is True
    assert "REDACTED" in str(resolved)


def test_runner_blocks_out_of_domain_and_classifies(tmp_path: Path):
    primitives = MockComputerUsePrimitives()
    client = MockGeminiComputerUseClient(script=[
        {"action_type": "navigate", "url": "https://evil.example.com/", "reason": "bad"},
        {"action_type": "navigate", "url": "https://evil.example.com/", "reason": "bad"},
        {"action_type": "navigate", "url": "https://evil.example.com/", "reason": "bad"},
        {"action_type": "navigate", "url": "https://evil.example.com/", "reason": "bad"},
    ])
    runner = ComputerUseRunner(primitives=primitives, gemini_client=client, artifacts_dir=tmp_path, mode="local_spike", max_actions_per_step=3)
    plan = load_golden()
    # Keep only first case/step for determinism
    plan["cases"] = [plan["cases"][0].copy()]
    plan["cases"][0]["steps"] = [plan["cases"][0]["steps"][0]]
    summary = runner.run(run_id="run-blocked-domain", plan=plan)
    assert summary.steps[0].status in {"blocked", "fail_agent"}
    assert summary.steps[0].validation["errors"] or summary.steps[0].status == "blocked"


def test_runner_retries_with_fallback_and_passes(tmp_path: Path):
    primitives = MockComputerUsePrimitives()
    # First attempt proposes a valid action but primitive will succeed; runner passes.
    # Retry path exercised via blocked-then-good script.
    client = MockGeminiComputerUseClient(script=[
        {"action_type": "navigate", "url": "https://evil.example.com/", "reason": "bad domain"},
        {"action_type": "navigate", "url": "https://testradius.dev/", "reason": "retry fallback"},
        {"action_type": "assert", "reason": "ok"},
        {"action_type": "click", "x": 100, "y": 100, "reason": "ok"},
    ])
    runner = ComputerUseRunner(primitives=primitives, gemini_client=client, artifacts_dir=tmp_path, mode="local_spike", max_actions_per_step=6)
    summary = runner.run(run_id="run-retry", plan=load_golden())
    statuses = [s.status for s in summary.steps]
    # First step needed 2 attempts (blocked then pass); overall should have passes.
    assert "pass" in statuses
    # Trace records attempts
    trace = (tmp_path / "run-retry" / "action_trace.jsonl").read_text()
    assert '"attempt": 2' in trace


def test_whole_plan_mode_is_labeled_non_default(tmp_path: Path):
    primitives = MockComputerUsePrimitives()
    client = MockGeminiComputerUseClient(script=[
        {"action_type": "navigate", "url": "https://testradius.dev/", "reason": "x"},
        {"action_type": "assert", "reason": "x"},
        {"action_type": "click", "x": 10, "y": 10, "reason": "x"},
    ])
    runner = ComputerUseRunner(primitives=primitives, gemini_client=client, artifacts_dir=tmp_path, mode="local_spike")
    summary = runner.run(run_id="run-whole", plan=load_golden(), loop="whole_plan")
    assert summary.mode == "whole_plan"
    progress_text = json.dumps(summary.progress)
    assert "Option A" in progress_text or "whole-plan" in progress_text
