"""Validation and quality gates for CompiledExecutionTestPlan (STORY-E2B-008.2)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Union
from urllib.parse import urlparse

from harness.policy.redaction import Redactor

from .schema import CompiledExecutionTestPlan, PlanCase, PlanStep, PlanValidationIssue

VAGUE_ASSERTION_PATTERNS = [
    re.compile(r"\bverify it works\b", re.I),
    re.compile(r"\bworks (as expected|correctly|fine)\b", re.I),
    re.compile(r"\bshould work\b", re.I),
    re.compile(r"\blooks? good\b", re.I),
    re.compile(r"\beverything (is )?ok\b", re.I),
    re.compile(r"\bno issues\b", re.I),
    re.compile(r"\bfunctions? properly\b", re.I),
    re.compile(r"\bas intended\b", re.I),
]
SECRET_ASSIGNMENT = re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd|authorization|cookie|session|private[_-]?key)\b\s*[:=]\s*['\"]?([^\s'\",}{]{8,})")
ENV_REF = re.compile(r"^\{\{\s*(env\.[A-Z][A-Z0-9_]*|test_data\.[A-Za-z0-9_.-]+|secrets?\.[A-Z][A-Z0-9_]*)\s*\}\}$")
ATOMICITY_HINTS = re.compile(r"\b(and then|then also|after that also|and verify .* and .*)\b", re.I)


@dataclass
class ValidationResult:
    ok: bool
    issues: List[PlanValidationIssue] = field(default_factory=list)
    warnings: List[PlanValidationIssue] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def errors(self) -> List[PlanValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "error_count": len(self.errors),
            "warning_count": len([i for i in self.issues if i.severity == "warning"]) + len(self.warnings),
            "issues": [i.model_dump() for i in self.issues],
            "warnings": [w.model_dump() for w in self.warnings],
            "metadata": self.metadata,
        }


class CompiledPlanValidator:
    def __init__(self, *, redactor: Optional[Redactor] = None):
        self.redactor = redactor or Redactor()

    def validate(
        self,
        plan: Union[CompiledExecutionTestPlan, Dict[str, Any]],
        *,
        mode: str = "production",  # production|local_spike
        provided_acs: Optional[Sequence[str]] = None,
        require_human_review_for_production: bool = True,
    ) -> ValidationResult:
        issues: List[PlanValidationIssue] = []
        warnings: List[PlanValidationIssue] = []
        try:
            obj = plan if isinstance(plan, CompiledExecutionTestPlan) else CompiledExecutionTestPlan.model_validate(plan)
        except Exception as e:
            issues.append(PlanValidationIssue(code="schema_invalid", message=f"Schema validation failed: {e}", path="$"))
            return ValidationResult(ok=False, issues=issues, warnings=warnings)

        self._check_target(obj, issues)
        self._check_preconditions(obj, issues)
        self._check_constraints(obj, issues)
        self._check_cases_steps(obj, issues, warnings)
        self._check_secrets(obj, issues)
        self._check_review_status(obj, issues, warnings, mode=mode, require=require_human_review_for_production)
        self._check_ac_coverage(obj, provided_acs, warnings)
        ok = not any(i.severity == "error" for i in issues)
        # attach validation errors to quality gate copy metadata for convenience
        meta = {"mode": mode, "cases": len(obj.cases), "steps": len(obj.all_steps()), "plan_id": obj.plan_id}
        return ValidationResult(ok=ok, issues=issues, warnings=warnings, metadata=meta)

    def _err(self, issues: List[PlanValidationIssue], code: str, message: str, path: str) -> None:
        issues.append(PlanValidationIssue(code=code, message=message, path=path, severity="error"))

    def _warn(self, warnings: List[PlanValidationIssue], code: str, message: str, path: str) -> None:
        warnings.append(PlanValidationIssue(code=code, message=message, path=path, severity="warning"))

    def _check_target(self, plan: CompiledExecutionTestPlan, issues: List[PlanValidationIssue]) -> None:
        base = (plan.sut.base_url or "").strip() if plan.sut else ""
        if not base:
            self._err(issues, "missing_target", "Missing SUT base_url/target.", "sut.base_url")
            return
        parsed = urlparse(base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            self._err(issues, "invalid_target", f"base_url must be an http(s) URL: {base}", "sut.base_url")

    def _check_preconditions(self, plan: CompiledExecutionTestPlan, issues: List[PlanValidationIssue]) -> None:
        pre = [p for p in (plan.preconditions or []) if str(p).strip() and str(p).strip().lower() not in {"none", "n/a", "na"}]
        has_case_pre = any(getattr(c, "preconditions", None) for c in plan.cases)
        if not pre and not has_case_pre:
            self._err(issues, "missing_preconditions", "Plan must include preconditions (or case preconditions).", "preconditions")

    def _check_constraints(self, plan: CompiledExecutionTestPlan, issues: List[PlanValidationIssue]) -> None:
        c = plan.constraints
        if not c:
            self._err(issues, "missing_constraints", "Missing constraints block.", "constraints")
            return
        allowed = [d for d in (c.allowed_domains or []) if str(d).strip()]
        allowed_urls = [u for u in (c.allowed_urls or []) if str(u).strip()]
        if not allowed and not allowed_urls:
            self._err(issues, "missing_allowed_domains", "constraints.allowed_domains/allowed_urls must be present.", "constraints.allowed_domains")
        elif plan.sut and plan.sut.base_url:
            host = urlparse(plan.sut.base_url).netloc.lower()
            host_name = host.split("@")[-1].split(":")[0]
            domain_ok = any(host_name == d.lower().strip().split(":")[0] or host_name.endswith("." + d.lower().strip().split(":")[0]) for d in allowed)
            url_ok = any(plan.sut.base_url.startswith(u) for u in allowed_urls)
            if not domain_ok and not url_ok:
                self._err(issues, "target_not_allowed", f"base_url host '{host_name}' is not covered by constraints.allowed_domains/allowed_urls.", "constraints.allowed_domains")
        if not getattr(c, "max_runtime_s", None):
            self._err(issues, "missing_timeout", "constraints.max_runtime_s is required.", "constraints.max_runtime_s")

    def _check_cases_steps(self, plan: CompiledExecutionTestPlan, issues: List[PlanValidationIssue], warnings: List[PlanValidationIssue]) -> None:
        if not plan.cases:
            self._err(issues, "missing_cases", "Plan must include at least one case/flow with steps.", "cases")
            return
        seen_case_ids: Set[str] = set()
        for ci, case in enumerate(plan.cases):
            cpath = f"cases[{ci}]"
            if case.case_id in seen_case_ids:
                self._err(issues, "duplicate_case_id", f"Duplicate case_id '{case.case_id}'.", f"{cpath}.case_id")
            seen_case_ids.add(case.case_id)
            if not case.steps:
                self._err(issues, "missing_steps", "Each case must include steps.", f"{cpath}.steps")
                continue
            seen_step_ids: Set[str] = set()
            for si, step in enumerate(case.steps):
                spath = f"{cpath}.steps[{si}]"
                if step.step_id in seen_step_ids:
                    self._err(issues, "duplicate_step_id", f"Duplicate step_id '{step.step_id}' in case {case.case_id}.", f"{spath}.step_id")
                seen_step_ids.add(step.step_id)
                self._check_step(case, step, spath, issues, warnings)

    def _check_step(self, case: PlanCase, step: PlanStep, spath: str, issues: List[PlanValidationIssue], warnings: List[PlanValidationIssue]) -> None:
        sc = [s for s in (step.success_criteria or []) if str(s).strip()]
        if not sc:
            self._err(issues, "missing_success_criteria", "Every step must have specific, testable success_criteria.", f"{spath}.success_criteria")
        for i, text in enumerate(sc):
            for pat in VAGUE_ASSERTION_PATTERNS:
                if pat.search(text):
                    self._err(issues, "vague_success_criteria", f"Success criteria is vague: '{text}'. Make it observable/testable.", f"{spath}.success_criteria[{i}]")
                    break
        if not getattr(step, "timeout_s", None):
            self._err(issues, "missing_step_timeout", "Each step must define timeout_s.", f"{spath}.timeout_s")
        if not getattr(step, "max_attempts", None):
            self._err(issues, "missing_max_attempts", "Each step must define max_attempts.", f"{spath}.max_attempts")
        ev = step.normalized_evidence()
        if not (ev.screenshot_on_failure or ev.action_trace or ev.screenshot_after or ev.screenshot_before or ev.dom_text):
            self._err(issues, "missing_evidence", "Each step must define evidence requirements.", f"{spath}.evidence")
        if not (step.fallback_instructions or []):
            self._warn(warnings, "missing_fallback", "Step has no fallback_instructions; add hints for target-not-found/recovery.", f"{spath}.fallback_instructions")
        if step.destructive or step.action_type in {"upload_ref"} and "delete" in step.intent.lower():
            pass
        if step.destructive and not step.requires_human_approval:
            self._err(issues, "destructive_requires_approval", "Destructive steps must set requires_human_approval=true.", f"{spath}.requires_human_approval")
        if ATOMICITY_HINTS.search(step.intent or "") and len(sc) > 2:
            self._warn(warnings, "step_may_not_be_atomic", "Step intent suggests multiple actions; consider splitting into atomic steps.", f"{spath}.intent")

    def _check_secrets(self, plan: CompiledExecutionTestPlan, issues: List[PlanValidationIssue]) -> None:
        raw = json.dumps(plan.to_json(), ensure_ascii=False)
        # Redactor catches common patterns; also check env refs are allowed.
        for m in SECRET_ASSIGNMENT.finditer(raw):
            value = m.group(3)
            if ENV_REF.fullmatch(value.strip()):
                continue
            start = max(0, m.start() - 30)
            ctx = raw[start:m.end() + 10]
            self._err(issues, "inline_secret", f"Possible inline secret detected near: {ctx}", "$")
            break
        # scan specific high-risk fields
        for ci, case in enumerate(plan.cases):
            for si, step in enumerate(case.steps):
                inp = step.input
                if isinstance(inp, str):
                    if ENV_REF.fullmatch(inp.strip()) or inp.strip().startswith("{{test_data."):
                        continue
                    if SECRET_ASSIGNMENT.search(f"password={inp}") or SECRET_ASSIGNMENT.search(f"token={inp}"):
                        # heuristic: input value itself looks secret-like in key=value form unlikely here; rely on full scan
                        pass
                    if re.search(r"(?i)\b(sk-[A-Za-z0-9]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z\-_]{20,})\b", inp):
                        self._err(issues, "inline_secret", "Step input appears to contain an inline API/credential token.", f"cases[{ci}].steps[{si}].input")
                if isinstance(inp, dict):
                    for k, v in inp.items():
                        if re.search(r"(?i)(password|token|secret|api.?key)", str(k)) and isinstance(v, str) and not ENV_REF.fullmatch(v.strip()):
                            self._err(issues, "inline_secret", f"Step input field '{k}' appears to contain an inline secret; use env/test_data ref.", f"cases[{ci}].steps[{si}].input.{k}")
        # ensure auth secret refs are names only
        for k, v in (plan.sut.auth_secret_refs or {}).items():
            if isinstance(v, str) and (len(v) > 80 or " " in v.strip() or v.startswith("sk-") or v.startswith("ghp_")):
                self._err(issues, "inline_secret", f"sut.auth_secret_refs.{k} must be an env/secret *name*, not a value.", f"sut.auth_secret_refs.{k}")

    def _check_review_status(self, plan: CompiledExecutionTestPlan, issues: List[PlanValidationIssue], warnings: List[PlanValidationIssue], *, mode: str, require: bool) -> None:
        status = (plan.quality_gate.review_status if plan.quality_gate else "draft") or "draft"
        if mode == "production" and require and status != "approved":
            self._err(issues, "review_not_approved", "Autonomous production execution requires quality_gate.review_status='approved' (human review gate).", "quality_gate.review_status")
        elif status == "draft":
            self._warn(warnings, "draft_plan", "Plan is in draft review status; acceptable for local spike only.", "quality_gate.review_status")

    def _check_ac_coverage(self, plan: CompiledExecutionTestPlan, provided_acs: Optional[Sequence[str]], warnings: List[PlanValidationIssue]) -> None:
        if not provided_acs:
            return
        hay = " \n ".join([
            plan.objective or "", plan.title or "",
            *[c.title for c in plan.cases],
            *[s.intent + " " + " ".join(s.success_criteria) for s in plan.all_steps()],
        ]).lower()
        missing = []
        for ac in provided_acs:
            acs = str(ac).strip()
            if not acs:
                continue
            # simple keyword overlap heuristic
            tokens = [t for t in re.findall(r"[a-z0-9]{4,}", acs.lower()) if t not in {"user", "should", "when", "then", "given", "with", "that", "from", "able", "must"}]
            if tokens and not any(t in hay for t in tokens[:8]):
                missing.append(acs[:120])
        if missing:
            self._warn(warnings, "ac_coverage_gap", f"Provided ACs may not be covered by plan: {missing[:5]}", "quality_gate.coverage_notes")
            if plan.quality_gate and not plan.quality_gate.coverage_notes:
                plan.quality_gate.coverage_notes.append(f"Potential AC coverage gaps: {missing[:5]}")
