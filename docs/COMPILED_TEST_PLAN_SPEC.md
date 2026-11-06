# Compiled Execution Test Plan — Spec (EPIC-E2B-008)

A `CompiledExecutionTestPlan` is the **single source of truth** for computer-use execution. It is the only payload sent to E2B sandboxes (plus minimal runtime config). Raw Jira/Figma/PRD/context payloads stay control-plane only (see `docs/MCP_CONTEXT_INTAKE.md`).

Reference implementation: `harness/testplan/schema.py` (`schema_version=1.0.0`); quality gate: `harness/testplan/validator.py`.

## Required shape

| Field | Notes |
|---|---|
| `schema_version`, `plan_id`, `title`, `objective` | Versioned, stable IDs |
| `source_refs[]` | Ticket/doc/Figma/GitHub refs — **no secrets** |
| `generated_at`, `generator{model,prompt_version}` | Compiler provenance |
| `sut{base_url, environment, viewport, auth_mode, auth_secret_refs}` | `base_url` required; `auth_secret_refs` = env/secret *names* only |
| `preconditions[]` | Required state/setup before step 1 |
| `test_data[]` | Named fixtures; secrets by `secret_ref` name only |
| `constraints{allowed_domains, max_runtime_s, max_steps, destructive_policy}` | Validator enforces domain coverage |
| `cases[]` (alias `flows[]`) | Each: `case_id`, `title`, `priority`, `type` (happy/edge/negative/accessibility/visual/smoke), `tags`, `steps[]` |
| `steps[]` | `step_id`, `ordinal`, `intent`, `action_type` (navigate/click/type/select/scroll/hover/keypress/wait/assert/upload_ref/note), `target{description + text/role/label/region/hints}`, `input` (`{{test_data.x}}`/`{{env.VAR}}` — never inline secret), `success_criteria` (observable, testable), `failure_signals`, `evidence{before/after/on_failure}`, `timeout_s`, `max_attempts`, `fallback_instructions`, `on_fail` (stop_case/continue_and_report/mark_blocked), `requires_human_approval`, `destructive` |
| `postconditions[]`, `cleanup[]` | Teardown |
| `oracle_notes`, `execution_hints_for_computer_use` | Pass/fail + agent hints |
| `quality_gate{compiled_by, review_status, coverage_notes}` | `draft\|human_reviewed\|approved` — production requires `approved` |

## Validator (`CompiledPlanValidator`)
Rejects: missing/invalid target, missing preconditions/cases/steps, missing/vague `success_criteria` (e.g. “verify it works”), missing evidence/timeouts/max_attempts, target outside `allowed_domains`, inline secrets/token values, destructive steps without approval flag. Warnings: missing fallbacks, non-atomic steps, AC-coverage gaps. Modes: `production` (requires approved) vs `local_spike` (draft allowed).

Golden example: `evals/fixtures/compiled_test_plan.valid.json`.

## Compiler (008.3)
`harness/testplan/compiler.py` + `harness/testplan/prompts/v1.py` compile normalized `ContextBundle` → validated plan with bounded repair. Live Gemini requires `google-genai` + `GEMINI_API_KEY`; tests use mocked generators.

## Example
See `docs/examples/compiled_test_plan.008.3.sample.json` and `evals/fixtures/computer_use_tiny_plan.json` (2-step golden spike).
