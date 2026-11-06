"""Prompt template v1 for CompiledExecutionTestPlan generation."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Sequence

PROMPT_VERSION = "testplan-compiler-v1"

# Compact schema contract (execution-critical). Full Pydantic schema lives in harness/testplan/schema.py.
SCHEMA_CONTRACT = {
    "schema_version": "1.0.0",
    "plan_id": "string",
    "title": "string",
    "objective": "string",
    "source_refs": [{"kind": "ticket|doc|figma|github|manual|mcp", "ref": "string", "title?": "string", "uri?": "string"}],
    "generator": {"model": "string", "prompt_version": PROMPT_VERSION},
    "sut": {"base_url": "https://...", "environment": "string", "browser?": "string", "viewport?": {"width": 1440, "height": 900}, "auth_mode": "none|manual_prelogin|test_account_ref", "auth_secret_refs": {"password": "ENV_VAR_NAME_ONLY"}},
    "preconditions": [{"id?": "P1", "description": "required state/setup"}],
    "test_data": [{"name": "x", "value?": "non-secret", "secret_ref?": "ENV_VAR_NAME_ONLY"}],
    "constraints": {"allowed_domains": ["example.com"], "destructive_action_policy": "require_human_approval", "max_runtime_s": 900, "max_steps": 200, "stop_conditions": [], "data_handling": [], "redaction_rules": []},
    "cases": [{
        "case_id": "C1", "title": "string", "priority": "high|medium|low", "type": "happy|edge|negative|regression|accessibility|visual|smoke", "tags": [],
        "steps": [{
            "step_id": "C1-S1", "ordinal": 1, "intent": "human intent", "action_type": "navigate|click|type|select|scroll|hover|keypress|wait|assert|upload_ref|note",
            "target": {"description": "semantic target", "text?": "", "role?": "", "label?": "", "region?": "", "selector_hint?": "optional"},
            "input": "value or {{test_data.x}} or {{env.VAR_NAME}}; never inline secret",
            "success_criteria": ["observable, specific, testable criterion"],
            "failure_signals": ["observable failure"],
            "evidence": {"screenshot_before": False, "screenshot_after": True, "screenshot_on_failure": True, "action_trace": True},
            "max_attempts": 2, "timeout_s": 30,
            "fallback_instructions": ["what to try if target not found"],
            "on_fail": "stop_case|continue_and_report|mark_blocked",
            "requires_human_approval": False
        }]
    }],
    "postconditions": [], "cleanup": [],
    "oracle_notes": ["what constitutes pass/fail; acceptable variations"],
    "execution_hints_for_computer_use": ["prefer visible labels over coordinates", "verify page loaded before acting"],
    "quality_gate": {"compiled_by": "gemini", "review_status": "draft", "validation_errors": [], "coverage_notes": []}
}

# Minimal few-shot/golden excerpt (distilled from evals/fixtures/compiled_test_plan.valid.json)
GOLDEN_EXCERPT = {
    "plan_id": "ctp-golden-homepage-001",
    "title": "Homepage hero CTA smoke (golden sample)",
    "objective": "Verify the homepage loads and the primary hero CTA is visible, accessible, and routes to the contact form without errors.",
    "sut": {"base_url": "https://testradius.dev", "environment": "staging", "browser": "chromium", "viewport": {"width": 1440, "height": 900}, "auth_mode": "none"},
    "preconditions": [{"id": "P1", "description": "Target site is reachable."}],
    "constraints": {"allowed_domains": ["testradius.dev"], "destructive_action_policy": "require_human_approval", "max_runtime_s": 600, "max_steps": 50},
    "cases": [{"case_id": "C1", "title": "Homepage loads and hero CTA is actionable", "priority": "high", "type": "smoke", "steps": [{
        "step_id": "C1-S1", "ordinal": 1, "intent": "Open the homepage and confirm the page has loaded.", "action_type": "navigate",
        "target": {"description": "Browser address/navigation to the site root", "region": "browser chrome"}, "input": "https://testradius.dev/",
        "success_criteria": ["Browser URL is https://testradius.dev/ or canonical homepage on the same domain.", "A visible primary heading or hero region is rendered (not blank/error page)."],
        "failure_signals": ["Navigation timeout", "HTTP 4xx/5xx", "Blank page"], "evidence": {"screenshot_after": True, "screenshot_on_failure": True, "action_trace": True},
        "max_attempts": 2, "timeout_s": 45, "fallback_instructions": ["Refresh once if stalled; wait up to 20s for main content."], "on_fail": "stop_case", "requires_human_approval": False
    }]}],
    "quality_gate": {"compiled_by": "golden-fixture", "review_status": "human_reviewed", "validation_errors": [], "coverage_notes": []}
}


def build_compile_messages(
    *,
    context_bundle: Mapping[str, Any],
    sut_config: Mapping[str, Any],
    run_config: Optional[Mapping[str, Any]] = None,
    provided_acs: Optional[Sequence[str]] = None,
) -> List[Dict[str, str]]:
    system = (
        "You are a senior QA test architect and execution planner. "
        "Compile normalized product context into a CompiledExecutionTestPlan JSON for Gemini computer-use execution in an E2B desktop sandbox. "
        "The plan must be self-contained and executable without additional user instructions or raw context uploads to the sandbox.\n\n"
        "Hard requirements:\n"
        "- Output ONLY valid JSON matching the schema contract. No markdown fences, no commentary.\n"
        "- No vague assertions (never 'verify it works', 'looks good', 'as expected' without observable criteria).\n"
        "- Every step must have specific, observable/testable success_criteria, failure_signals, timeout_s, max_attempts, fallback_instructions, and evidence (include screenshot_on_failure and/or action_trace).\n"
        "- Never include inline secrets/tokens/passwords/API keys. Use {{env.VAR_NAME}} or {{test_data.name}} refs; put secret refs as env var names only.\n"
        "- Include preconditions, allowed_domains (covering base_url), constraints, postconditions/cleanup as applicable, oracle_notes, and execution_hints_for_computer_use.\n"
        "- Expand acceptance criteria into concrete cases/steps; include happy path and, when relevant, negative/edge and key visual/UX/accessibility checks.\n"
        "- Distill Figma/design intent and ticket nuances into textual step targets/oracles (sandbox will not load raw Figma).\n"
        "- Mark destructive/risky steps with requires_human_approval=true and appropriate on_fail.\n"
        "- Use atomic steps where practical; prefer visible labels/roles/regions over coordinates in targets/fallbacks.\n"
        "- Set quality_gate.review_status='draft' and quality_gate.compiled_by='gemini'."
    )
    user = {
        "task": "Compile the normalized context into a high-quality CompiledExecutionTestPlan JSON.",
        "schema_contract": SCHEMA_CONTRACT,
        "golden_excerpt": GOLDEN_EXCERPT,
        "normalized_context_bundle": _redacted_jsonable(context_bundle),
        "sut_runtime_config": _redacted_jsonable(sut_config),
        "run_config": _redacted_jsonable(run_config or {}),
        "provided_acceptance_criteria": list(provided_acs or []),
        "output_requirements": [
            "Return ONLY the JSON object.",
            "Ensure base_url host is included in constraints.allowed_domains.",
            "Ensure every case has steps and every step is executable by computer-use from the plan alone.",
        ],
    }
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user, ensure_ascii=False, indent=2)}]


def build_repair_messages(
    *,
    previous_json: str,
    validation_errors: Sequence[Mapping[str, Any]],
    context_bundle: Mapping[str, Any],
    sut_config: Mapping[str, Any],
) -> List[Dict[str, str]]:
    system = (
        "You repair CompiledExecutionTestPlan JSON to satisfy schema and QA quality gates. "
        "Return ONLY corrected JSON. No markdown fences. Preserve intent and coverage while fixing every listed issue. "
        "Do not add inline secrets. Keep success criteria observable and specific."
    )
    user = {
        "task": "Fix the compiled test plan JSON so it passes validation/quality checks.",
        "validation_errors": list(validation_errors),
        "previous_plan_json": previous_json,
        "normalized_context_bundle_summary": {
            "ticket_id": context_bundle.get("ticket_id"),
            "title": context_bundle.get("title"),
            "acceptance_criteria": context_bundle.get("acceptance_criteria", [])[:20],
            "source_refs": context_bundle.get("source_refs", [])[:10],
        },
        "sut_runtime_config": _redacted_jsonable(sut_config),
    }
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user, ensure_ascii=False, indent=2)}]


def _redacted_jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except Exception:
        return json.loads(json.dumps(value, default=str))
