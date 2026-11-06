import json
from pathlib import Path

from harness.testplan import CompiledExecutionTestPlan, GeminiTestPlanCompiler

GOLDEN_CONTEXT = Path(__file__).resolve().parents[3] / "docs" / "examples" / "context_bundle.normalized.008.1.json"
GOLDEN_PLAN = Path(__file__).resolve().parents[3] / "evals" / "fixtures" / "compiled_test_plan.valid.json"


class MockGenerator:
    def __init__(self, responses):
        self.model = "mock-gemini"
        self.responses = list(responses)
        self.calls = []

    def generate(self, *, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        if not self.responses:
            raise AssertionError("No more mock responses")
        return self.responses.pop(0)


def sut_config():
    return {
        "base_url": "https://testradius.dev",
        "environment": "staging",
        "browser": "chromium",
        "viewport": {"width": 1440, "height": 900},
        "auth_mode": "none",
    }


def valid_plan_dict():
    plan = json.loads(GOLDEN_PLAN.read_text())
    plan["plan_id"] = "ctp-compiled-mock-001"
    plan["quality_gate"]["review_status"] = "draft"  # compiler output starts draft
    plan["generator"] = {"model": "mock-gemini", "prompt_version": "testplan-compiler-v1"}
    return plan


def test_compiler_produces_valid_plan_from_golden_context_and_saves(tmp_path: Path):
    ctx = json.loads(GOLDEN_CONTEXT.read_text())
    compiler = GeminiTestPlanCompiler(generator=MockGenerator([json.dumps(valid_plan_dict())]), max_repair_attempts=1)
    res = compiler.compile(context_bundle=ctx, sut_config=sut_config(), run_id="run-0083", artifacts_dir=tmp_path, mode="local_spike")
    assert res.ok, res.to_dict()
    assert isinstance(res.plan, CompiledExecutionTestPlan)
    assert res.plan.sut.base_url == "https://testradius.dev"
    assert res.plan.quality_gate.review_status == "draft"
    assert res.attempts == 1
    assert not res.repaired
    assert res.artifact_path and Path(res.artifact_path).exists()
    saved = json.loads(Path(res.artifact_path).read_text())
    assert saved["generator"]["prompt_version"] == "testplan-compiler-v1"
    assert saved["generator"]["model"] == "mock-gemini"
    assert saved["quality_gate"]["validated_at"]


def test_compiler_repairs_invalid_output_with_bounded_retries(tmp_path: Path):
    ctx = json.loads(GOLDEN_CONTEXT.read_text())
    bad = valid_plan_dict()
    bad["cases"][0]["steps"][0]["success_criteria"] = ["verify it works"]
    bad["preconditions"] = []
    good = valid_plan_dict()
    good["cases"][0]["steps"][0]["success_criteria"] = ["Homepage displays a visible hero section and primary navigation within 45 seconds."]
    gen = MockGenerator([json.dumps(bad), json.dumps(good)])
    compiler = GeminiTestPlanCompiler(generator=gen, max_repair_attempts=2)
    res = compiler.compile(context_bundle=ctx, sut_config=sut_config(), run_id="run-repair", artifacts_dir=tmp_path)
    assert res.ok, res.to_dict()
    assert res.repaired is True
    assert res.attempts == 2
    assert len(gen.calls) == 2
    assert "validation_errors" in gen.calls[1]["user"]


def test_compiler_fails_after_bounded_repair_attempts(tmp_path: Path):
    ctx = json.loads(GOLDEN_CONTEXT.read_text())
    bad = valid_plan_dict()
    bad["cases"][0]["steps"][0]["success_criteria"] = ["verify it works"]
    gen = MockGenerator([json.dumps(bad), json.dumps(bad), json.dumps(bad)])
    compiler = GeminiTestPlanCompiler(generator=gen, max_repair_attempts=2)
    res = compiler.compile(context_bundle=ctx, sut_config=sut_config(), run_id="run-fail", artifacts_dir=tmp_path)
    assert not res.ok
    assert res.error
    assert res.validation is not None
    assert any(i.code == "vague_success_criteria" for i in res.validation.issues)
    assert len(gen.calls) == 3


def test_compiler_extracts_json_from_fenced_output(tmp_path: Path):
    ctx = json.loads(GOLDEN_CONTEXT.read_text())
    wrapped = "```json\n" + json.dumps(valid_plan_dict()) + "\n```"
    compiler = GeminiTestPlanCompiler(generator=MockGenerator([wrapped]))
    res = compiler.compile(context_bundle=ctx, sut_config=sut_config(), run_id="run-fence", artifacts_dir=tmp_path)
    assert res.ok, res.to_dict()


def test_compiler_redacts_metadata_and_preserves_env_refs(tmp_path: Path):
    ctx = json.loads(GOLDEN_CONTEXT.read_text())
    plan = valid_plan_dict()
    plan["sut"]["auth_mode"] = "test_account_ref"
    plan["sut"]["auth_secret_refs"] = {"password": "TEST_USER_PASSWORD"}  # name only, ok
    plan["cases"][0]["steps"][1]["input"] = "{{env.TEST_USER_EMAIL}}"
    compiler = GeminiTestPlanCompiler(generator=MockGenerator([json.dumps(plan)]))
    res = compiler.compile(context_bundle=ctx, sut_config=sut_config(), run_id="run-redact", artifacts_dir=tmp_path)
    assert res.ok, res.to_dict()
    saved = json.loads(Path(res.artifact_path).read_text())
    assert saved["sut"]["auth_secret_refs"]["password"] == "TEST_USER_PASSWORD"
    assert "{{env.TEST_USER_EMAIL}}" in json.dumps(saved)
    assert "sk-" not in json.dumps(saved)
