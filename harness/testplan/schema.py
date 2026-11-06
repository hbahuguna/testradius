"""CompiledExecutionTestPlan schema — contract for Gemini computer-use execution.

The compiled plan is the single source of truth for execution. It must be detailed
enough that no additional user instructions/raw context are needed in the sandbox.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA_VERSION = "1.0.0"
ReviewStatus = Literal["draft", "human_reviewed", "approved"]
ActionType = Literal[
    "navigate", "click", "type", "select", "scroll", "hover", "keypress", "wait", "assert", "upload_ref", "note",
]
OnFailAction = Literal["stop_case", "continue_and_report", "mark_blocked"]
AuthMode = Literal["none", "manual_prelogin", "test_account_ref"]
CaseType = Literal["happy", "edge", "negative", "regression", "accessibility", "visual", "smoke", "other"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PlanValidationIssue(BaseModel):
    code: str
    message: str
    path: str = ""
    severity: Literal["error", "warning"] = "error"


class GeneratorInfo(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: Optional[str] = None
    prompt_version: Optional[str] = None
    compiler_version: Optional[str] = None
    temperature: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="allow")
    kind: str = Field(default="unknown", description="ticket|doc|figma|github|manual|mcp|url|other")
    ref: str
    title: Optional[str] = None
    uri: Optional[str] = None


class SUT(BaseModel):
    model_config = ConfigDict(extra="allow")
    base_url: str = Field(default="")
    environment: str = Field(default="unknown")
    build_version: Optional[str] = None
    browser: Optional[str] = None
    device_profile: Optional[str] = None
    locale: Optional[str] = None
    timezone: Optional[str] = None
    viewport: Dict[str, Any] = Field(default_factory=dict)
    auth_mode: AuthMode = "none"
    auth_secret_refs: Dict[str, str] = Field(
        default_factory=dict,
        description="Env/secret *names* only, never values (e.g. {'password': 'TEST_USER_PASSWORD'}).",
    )


class Precondition(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: Optional[str] = None
    description: str
    required: bool = True
    setup_hint: Optional[str] = None


class TestDataItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    value: Any = None
    description: Optional[str] = None
    secret_ref: Optional[str] = Field(default=None, description="Env var/secret name only, never value")
    source: Optional[str] = None


class Constraints(BaseModel):
    model_config = ConfigDict(extra="allow")
    allowed_domains: List[str] = Field(default_factory=list)
    allowed_urls: List[str] = Field(default_factory=list)
    destructive_action_policy: str = Field(default="require_human_approval")
    max_runtime_s: int = Field(default=900, ge=1)
    max_steps: int = Field(default=200, ge=1)
    stop_conditions: List[str] = Field(default_factory=list)
    data_handling: List[str] = Field(default_factory=list)
    redaction_rules: List[str] = Field(default_factory=list)


class StepTarget(BaseModel):
    model_config = ConfigDict(extra="allow")
    description: str = Field(..., min_length=1)
    text: Optional[str] = None
    role: Optional[str] = None
    label: Optional[str] = None
    region: Optional[str] = None
    selector_hint: Optional[str] = Field(default=None, description="Optional selector hint; semantic description remains primary")
    css_xpath_optional: Optional[str] = None


class StepEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")
    screenshot_before: bool = False
    screenshot_after: bool = False
    screenshot_on_failure: bool = True
    dom_text: bool = False
    action_trace: bool = True
    notes: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, v: Any) -> Any:
        if isinstance(v, (list, tuple, set)):
            vals = {str(x).lower() for x in v}
            return {
                "screenshot_before": "screenshot_before" in vals,
                "screenshot_after": "screenshot_after" in vals,
                "screenshot_on_failure": "screenshot_on_failure" in vals or "on_failure" in vals or "failure" in vals,
                "dom_text": "dom_text" in vals,
                "action_trace": "action_trace" in vals or "trace" in vals or True,
            }
        return v


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="allow")
    step_id: str
    ordinal: int = Field(..., ge=1)
    intent: str = Field(..., min_length=1)
    action_type: ActionType
    target: Union[StepTarget, str, Dict[str, Any]]
    input: Any = Field(default=None, description="Value or {{test_data.x}}/{{env.VAR_NAME}} ref; never inline secret")
    success_criteria: List[str] = Field(default_factory=list)
    failure_signals: List[str] = Field(default_factory=list)
    evidence: Union[StepEvidence, List[str], Dict[str, Any]] = Field(default_factory=StepEvidence)
    max_attempts: int = Field(default=2, ge=1)
    timeout_s: int = Field(default=30, ge=1)
    fallback_instructions: List[str] = Field(default_factory=list)
    on_fail: OnFailAction = "stop_case"
    requires_human_approval: bool = False
    destructive: bool = False
    notes: Optional[str] = None

    @field_validator("target", mode="before")
    @classmethod
    def _target(cls, v: Any) -> Any:
        if isinstance(v, str):
            return {"description": v}
        return v

    @field_validator("success_criteria", "failure_signals", "fallback_instructions", mode="before")
    @classmethod
    def _str_list(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        return [str(x) for x in v if str(x).strip()]

    def normalized_target(self) -> StepTarget:
        if isinstance(self.target, StepTarget):
            return self.target
        if isinstance(self.target, dict):
            return StepTarget.model_validate(self.target)
        return StepTarget(description=str(self.target))

    def normalized_evidence(self) -> StepEvidence:
        if isinstance(self.evidence, StepEvidence):
            return self.evidence
        return StepEvidence.model_validate(self.evidence)


class PlanCase(BaseModel):
    model_config = ConfigDict(extra="allow")
    case_id: str
    title: str
    priority: str = Field(default="medium")
    type: CaseType = "happy"
    tags: List[str] = Field(default_factory=list)
    steps: List[PlanStep] = Field(default_factory=list)
    preconditions: List[Union[Precondition, str, Dict[str, Any]]] = Field(default_factory=list)
    postconditions: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    cleanup: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)


class QualityGateStatus(BaseModel):
    model_config = ConfigDict(extra="allow")
    compiled_by: Optional[str] = None
    review_status: ReviewStatus = "draft"
    validation_errors: List[Union[str, Dict[str, Any], PlanValidationIssue]] = Field(default_factory=list)
    coverage_notes: List[str] = Field(default_factory=list)
    validated_at: Optional[str] = None


class CompiledExecutionTestPlan(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str = Field(default=SCHEMA_VERSION)
    plan_id: str
    title: str
    objective: str
    source_refs: List[Union[SourceRef, Dict[str, Any]]] = Field(default_factory=list)
    generated_at: str = Field(default_factory=utc_now_iso)
    generator: Union[GeneratorInfo, Dict[str, Any]] = Field(default_factory=GeneratorInfo)

    sut: SUT
    preconditions: List[Union[Precondition, str, Dict[str, Any]]] = Field(default_factory=list)
    test_data: List[Union[TestDataItem, Dict[str, Any]]] = Field(default_factory=list)
    constraints: Constraints = Field(default_factory=Constraints)
    cases: List[PlanCase] = Field(default_factory=list)
    postconditions: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    cleanup: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    oracle_notes: List[str] = Field(default_factory=list)
    execution_hints_for_computer_use: List[str] = Field(default_factory=list)
    quality_gate: QualityGateStatus = Field(default_factory=QualityGateStatus)

    @model_validator(mode="before")
    @classmethod
    def _aliases(cls, v: Any) -> Any:
        if isinstance(v, dict) and "cases" not in v and "flows" in v:
            v = dict(v)
            v["cases"] = v.pop("flows")
        return v

    def all_steps(self) -> List[PlanStep]:
        steps: List[PlanStep] = []
        for case in self.cases:
            steps.extend(case.steps)
        return steps

    def to_json(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")
