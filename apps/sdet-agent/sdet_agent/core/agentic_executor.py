"""Agentic executor: goal-driven, live-browser test execution.

Implements the Slack-style agentic testing flow:

    goal -> agent adapts (observe -> plan -> act) -> verify result

Instead of running a fixed script, the agent is given a high-level GOAL and a
live browser session. On each turn it observes the page (accessibility
snapshot), asks the LLM to decide the single next action, executes that action
against the browser, and repeats until the goal is reached or a stopping
condition is hit. Final assertions are verified explicitly so the run is still
validated like a deterministic test.

This is the "Agentic Testing" layer that sits on top of deterministic E2E in
the testing pyramid -- used for exploring complex UI, debugging flaky flows,
and reproducing production issues, not for high-frequency CI.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..core.events import (
    EV_DONE,
    EV_ERROR,
    EV_NODE,
    EV_THINKING,
    EV_TOOL_CALL,
    EV_TOOL_RESULT,
    _NoopEmitter,
)
from ..core.trace import ActionTrace, AssertionResult, ExecutionTrace
from ..guardrails.agentic_guardrails import (
    ALLOWED_AGENT_ACTIONS,
    check_action_allowed,
    should_stop,
)
from ..tools import browser_tools as bt
from ..reasoning.llm_factory import LLMFactory, LLMClientConfig
from ..reasoning.hy3_client import Hy3Client
from ..reasoning.qwen_client import QwenClient

logger = logging.getLogger("sdet_agent.agentic")

_PLANNER_SYSTEM = (
    "You are an expert SDET agentic tester. You are given a GOAL and the live "
    "state of a web page (an accessibility snapshot + URL). Decide the SINGLE "
    "next action that moves toward the goal. You may also declare the goal "
    "reached, or declare failure if you are stuck.\n\n"
    "PREFER ACCESSIBLE LOCATORS. The VISIBLE INTERACTIVE ELEMENTS list uses the "
    "format 'role|name' (e.g. 'button|Join Pilot', 'combobox|role', "
    "'textbox|First name'). Some elements also have a 'context' field showing "
    "parent/sibling text (e.g. 'button|Start Trial (context: Most Popular)'). "
    "When the GOAL specifies which element to interact with (e.g. 'on the Most "
    "Popular card, click Start Trial'), match the context field and include it "
    "as a third pipe segment: 'role|name|context' (e.g. 'button|Start Trial|"
    "Most Popular'). For elements without context, use 'role|name' as usual.\n\n"
    "Respond with ONLY a JSON object, no prose, no code fences. For example:\n"
    "{\n"
    '  "thought": "Click the Apply button to open the form",\n'
    '  "action": "click",\n'
    '  "target": "button|Apply",\n'
    '  "kind": "role",\n'
    '  "value": "",\n'
    '  "confidence": 0.9\n'
    "}\n\n"
    "Rules:\n"
    "- COMPLETE THE FULL USER FLOW before emitting 'done'. For a form test, "
    "this means: fill ALL fields, then click the submit button, then wait for "
    "or observe the success confirmation. Do NOT emit 'done' just because "
    "fields are filled — you must trigger the final action (submit, save, "
    "send, etc.) that produces the expected result.\n"
    "- NEVER emit 'done' as your first action. You MUST perform at least one "
    "type/click/select action before declaring done. The goal ALWAYS requires "
    "interacting with page elements.\n"
    "- The ASSERTIONS section tells you what must be visible AFTER the flow "
    "completes. Only emit 'done' when you believe those assertions would pass "
    "on the current page state.\n"
    "- Do NOT emit assert_visible or assert_text as step actions. The system "
    "automatically verifies assertions when you emit 'done'.\n"
    "- If the goal's element is ALREADY visible on the current page (e.g. a "
    "success message is shown), go straight to 'done' without extra clicks.\n"
    "- Use 'fail' only if you are truly stuck after retrying.\n"
    "- 'toggle' in the GOAL means a switch/checkbox element — look for switch or checkbox role, then click it.\n"
    "- 'assert_text': target = expected substring; value = optional scoping locator.\n"
    "- 'assert_url': value = regex pattern the current URL must match.\n"
)

_VALID_ACTIONS = {
    "navigate", "click", "type", "select", "wait",
    "assert_visible", "assert_text", "assert_url", "done", "fail",
}

_ACTION_ALIASES = {
    "fill": "type", "enter": "type", "input": "type", "write": "type",
    "choose": "select", "pick": "select",
    "open": "navigate", "goto": "navigate", "go_to": "navigate",
    "verify": "assert_visible", "check": "assert_visible", "assert": "assert_visible",
    "finish": "done", "complete": "done", "stop": "done",
}

# Locator/resolve errors cannot self-heal within a single run -- the planner
# needs the self-healer to rewrite the spec. Abort fast so the error feeds the
# heal loop instead of burning turns.
_LOCATOR_ERROR_HINTS = ("no element matched", "ambiguous", "strict mode violation", "element is not")


def _is_locator_error(detail: str) -> bool:
    d = (detail or "").lower()
    return any(h in d for h in _LOCATOR_ERROR_HINTS)


@dataclass
class AgenticResult:
    success: bool
    goal_reached: bool
    trace: ExecutionTrace
    error: Optional[str] = None
    generated_code: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "goal_reached": self.goal_reached,
            "error": self.error,
            "generated_code": self.generated_code,
            "trace": self.trace.to_dict(),
        }


def _default_factory() -> LLMFactory:
    return LLMFactory(
        [
            LLMClientConfig(name="hy3-free", client_class=Hy3Client),
            LLMClientConfig(name="qwen", client_class=QwenClient),
        ]
    )


def _extract_json(text: str) -> Optional[dict]:
    """Pull the first balanced JSON object out of an LLM reply."""
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                chunk = text[start : i + 1]
                try:
                    return json.loads(chunk)
                except json.JSONDecodeError:
                    break
    # Fallback: grab from the first '{' to the last '}' (tolerates prose
    # or stray braces before/after the real JSON object).
    last = text.rfind("}")
    if start != -1 and last > start:
        chunk = text[start : last + 1]
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            pass
    return None


def _extract_json_array(text: str) -> Optional[list]:
    """Pull the first balanced JSON array out of an LLM reply.

    Tolerates prose or markdown fences before/after the array.
    """
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("[")
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                chunk = text[start : i + 1]
                try:
                    return json.loads(chunk)
                except json.JSONDecodeError:
                    break
    return None


_BATCH_PLAN_SYSTEM = (
    "You are a test automation planner. Given a GOAL, ASSERTIONS, CURRENT URL, "
    "and VISIBLE INTERACTIVE ELEMENTS, produce the COMPLETE sequence of actions "
    "needed to achieve the goal in one shot.\n\n"
    "PREFER ACCESSIBLE LOCATORS. The VISIBLE INTERACTIVE ELEMENTS list uses the "
    "format 'role|name' (e.g. 'button|Apply', 'combobox|role', "
    "'textbox|First name'). Some elements also have a 'context' field showing "
    "parent/sibling text (e.g. 'button|Start Trial context: Most Popular'). "
    "Use kind='role' with the exact 'role|name' string.\n\n"
    "DISAMBIGUATION: When the GOAL specifies which element to interact with "
    "(e.g. 'on the Most Popular card, click Start Trial'), match the context "
    "field to find the correct element. Include the context text in the target "
    "as 'role|name|context' (e.g. 'button|Start Trial|Most Popular').\n\n"
    "Respond with ONLY a JSON object:\n"
    "{\n"
    '  "thought": "brief rationale for the plan",\n'
    '  "actions": [\n'
    '    {"action": "type", "target": "textbox|First Name", "kind": "role", "value": "Himanshu"},\n'
    '    {"action": "type", "target": "textbox|Last Name", "kind": "role", "value": "Bahuguna"},\n'
    '    {"action": "click", "target": "button|Submit Application", "kind": "role", "value": ""}\n'
    "  ]\n"
    "}\n\n"
    "When multiple elements share the same role+name, use context to disambiguate:\n"
    '  {"action": "click", "target": "button|Start Trial|data-tier=growth", "kind": "role"}\n'
    '  {"action": "click", "target": "button|Start Trial|data-tier=scale", "kind": "role"}\n\n'
    "Rules:\n"
    "- List ALL actions from first to last. For forms: fill every field, THEN click submit.\n"
    "- For <select> elements (combobox role), use action='type' with the OPTION LABEL as value.\n"
    "- For toggles/switches (switch role): use action='click'.\n"
    "- 'toggle' in the GOAL means a switch/checkbox element — look for switch or checkbox role.\n"
    "- Do NOT include assert_visible/assert_text actions — the system verifies automatically.\n"
    "- Do NOT emit 'done' or 'fail' as actions — just list the interaction steps.\n"
    "- If the goal says 'verify' or 'check', skip that step — the system handles assertions.\n"
    "- Maximum 20 actions."
)


def _extract_batch(out: str) -> Optional[list[dict]]:
    """Extract an actions list from LLM output (single JSON or JSON-in-prose)."""
    if not out:
        return None
    parsed = _extract_json(out)
    if not parsed:
        return None
    actions = parsed.get("actions")
    if isinstance(actions, list) and actions:
        return actions
    return None


def _extract_action_from_prose(text: str) -> Optional[dict]:
    """Fallback: parse a simple action from reasoning-model prose.

    Only triggers when there is NO JSON-like structure in the output.
    """
    if not text:
        return None
    if "{" in text:
        return None
    lower = text.lower()

    done_patterns = [
        r"(?:action[=:]\s*)?['\"]?done['\"]?",
        r"goal\s+(?:is\s+)?achieved",
        r"(?:should|will|can)\s+finish",
        r"no\s+further\s+action",
        r"test\s+is\s+complete",
    ]
    for pat in done_patterns:
        if re.search(pat, lower):
            return {"action": "done", "thought": "extracted from prose: goal achieved"}

    if re.search(r"(?:action[=:]\s*)?['\"]?fail['\"]?|cannot\s+proceed|stuck|unable\s+to", lower):
        return {"action": "fail", "thought": "extracted from prose: cannot proceed"}

    m = re.search(r"click\s+(?:on\s+)?(?:the\s+)?['\"]?(\w[\w\s|]*?)['\"]?(?:\s+button|\s+link|\s+element)?", lower)
    if m:
        target = m.group(1).strip()
        if "|" in target or any(r in target for r in ("button", "link", "textbox", "combobox")):
            return {"action": "click", "target": target, "kind": "auto", "thought": "extracted from prose"}

    m = re.search(r"type\s+['\"](.+?)['\"]\s+(?:in|into)\s+(?:the\s+)?['\"]?(\w[\w\s|]*?)['\"]?", lower)
    if m:
        return {"action": "type", "target": m.group(2).strip(), "kind": "auto", "value": m.group(1), "thought": "extracted from prose"}

    m = re.search(r"navigate\s+to\s+(https?://\S+)", text)
    if m:
        return {"action": "navigate", "target": m.group(1), "kind": "auto", "thought": "extracted from prose"}

    return None


class AgenticExecutor:
    """Runs a goal-driven agentic test against a live browser."""

    def __init__(
        self,
        llm_factory: Optional[LLMFactory] = None,
        emitter=None,
        max_turns: int = 30,
        backend: str = "mcp",
        headless: bool = True,
        assertion_retries: int = 2,
    ):
        self.llm = llm_factory or _default_factory()
        self.emitter = emitter or _NoopEmitter()
        self.max_turns = max_turns
        self.backend = backend
        self.headless = headless
        self.assertion_retries = assertion_retries

    # ------------------------------------------------------------------ #
    def run(
        self,
        goal: str,
        url: str,
        assertions: Optional[list[dict[str, Any]]] = None,
        constraints: Optional[dict[str, Any]] = None,
    ) -> AgenticResult:
        """Execute ``goal`` against ``url``; verify ``assertions`` at the end."""
        assertions = assertions or []
        constraints = constraints or {}
        stopping = constraints.get("stopping", {})
        trace = ExecutionTrace(goal=goal, url=url, backend=self.backend)
        start_ts = time.time()
        emitter = self.emitter

        emitter.emit(EV_NODE, node_id="agentic", role="agent", name="agentic-execute")
        start = bt.browser_start(headless=self.headless, backend=self.backend)
        if start.get("status") == "error":
            trace.error = start.get("error", "browser start failed")
            emitter.emit(EV_ERROR, message=trace.error)
            return AgenticResult(False, False, trace, trace.error)

        bt.browser_navigate(url)
        history: list[str] = []
        step_no = 0
        done_attempts = 0
        consecutive_failures = 0
        max_consecutive_failures = 3
        snap: dict[str, Any] = {"ok": False}

        try:
            # ── BATCH PLANNING: get full action sequence in one LLM call ──
            snap = bt.browser_snapshot()
            interactive = snap.get("interactive_elements", []) if snap.get("ok") else []
            current_url = snap.get("url", url)

            batch = self._plan_batch(goal, assertions, current_url, interactive, constraints)
            if batch:
                emitter.emit(EV_THINKING, node_id="agentic", text=f"batch plan: {len(batch)} actions")
                batch_ok = True
                for ba in batch:
                    act = ba.get("action", "fail")
                    act = _ACTION_ALIASES.get(act, act)
                    tgt = ba.get("target", "") or ba.get("element", "")
                    knd = ba.get("kind", "auto")
                    val = ba.get("value", "")
                    thought = ba.get("thought", "batch step")

                    emitter.emit(EV_THINKING, node_id="agentic", text=thought)

                    step_no += 1
                    ok, detail = self._execute_action(act, tgt, knd, val)
                    step = ActionTrace(
                        step=step_no, action=act, target=tgt, kind=knd, value=val,
                        ok=ok, thought=thought, detail=detail, url=current_url,
                        interactive_elements=interactive[:40], duration_ms=0.0, timestamp=time.time(),
                    )
                    trace.steps.append(step)
                    history.append(f"[{act}] {tgt} -> {'ok' if ok else 'FAIL: ' + detail}")
                    if not ok:
                        logger.warning("batch action failed: %s", detail)
                        if _is_locator_error(detail):
                            trace.error = f"batch: {act} on '{tgt}' failed: {detail}"
                            batch_ok = False
                            break
                        # Non-locator failure: fall back to step-by-step for remaining
                        batch_ok = False
                        break

                if batch_ok:
                    # Brief wait for page to settle after submit
                    import time as _time
                    _time.sleep(2)
                    # All batch steps succeeded — verify assertions
                    results = self._verify_assertions(assertions)
                    trace.assertions.extend(results)
                    if assertions and all(r.passed for r in results):
                        trace.goal_reached = True
                        trace.success = True
                    elif assertions:
                        failed = "; ".join(r.detail for r in results if not r.passed)
                        trace.error = f"assertions not met after batch: {failed}"
                    else:
                        performed = [s for s in trace.steps if s.action not in ("done", "fail", "navigate", "wait")]
                        if performed and all(s.ok for s in performed):
                            trace.goal_reached = True
                            trace.success = True
                        else:
                            trace.error = "batch completed but no assertions and no verified actions"
                # If batch failed, fall through to step-by-step below

            # ── STEP-BY-STEP FALLBACK: one LLM call per action ──
            if not trace.success:
              while step_no < self.max_turns:
                stop = should_stop(start_ts, step_no, self.max_turns, stopping)
                if not stop.allow:
                    trace.error = stop.reason
                    break

                snap = bt.browser_snapshot()
                interactive = snap.get("interactive_elements", []) if snap.get("ok") else []
                current_url = snap.get("url", url)
                plan = self._plan(goal, assertions, current_url, interactive, history, constraints)

                action = plan.get("action", "fail")
                action = _ACTION_ALIASES.get(action, action)
                if action not in _VALID_ACTIONS:
                    logger.warning("planner returned invalid action: %s (plan=%s)", action, plan)
                    plan["thought"] = f"invalid action from planner: {action}"
                    action = "fail"

                verdict = check_action_allowed(action, constraints)
                if not verdict.allow and action not in ("done", "fail"):
                    action = "fail"
                    plan["thought"] = verdict.reason

                # Assert actions should never be step actions — the system
                # verifies assertions automatically when 'done' is emitted.
                if action in ("assert_visible", "assert_text", "assert_url"):
                    history.append(f"[skip] assertion action {action} ignored — will verify on done")
                    continue

                target = plan.get("target", "") or plan.get("element", "")
                kind = plan.get("kind", "auto")
                value = plan.get("value", "")
                thought = plan.get("thought", "")

                emitter.emit(EV_THINKING, node_id="agentic", text=thought)

                if action == "done":
                    done_attempts += 1
                    # If the agent hasn't performed any real actions yet
                    # (type/click/select), this 'done' is premature — the
                    # planner is giving up before completing the flow.
                    performed = [s for s in trace.steps if s.action not in ("done", "fail", "navigate", "wait")]
                    if not performed:
                        reject_msg = (
                            "[done] REJECTED — you have NOT performed any form actions yet. "
                            "The goal requires interacting with page elements (filling fields, "
                            "clicking buttons, selecting options). You MUST perform these actions "
                            "before declaring done. Pick the next element and act on it."
                        )
                        history.append(reject_msg)
                        if done_attempts > self.assertion_retries:
                            trace.error = "planner kept declaring done without performing any form actions"
                            break
                        continue
                    results = self._verify_assertions(assertions)
                    trace.assertions.extend(results)
                    if assertions and all(r.passed for r in results):
                        trace.goal_reached = True
                        trace.success = True
                        break
                    if not assertions:
                        # No assertions were supplied: success is only valid if
                        # the agent actually performed actions and none failed.
                        # This prevents a vacuous "success" when the planner
                        # declares done without touching the page.
                        performed = [s for s in trace.steps if s.action not in ("done", "fail")]
                        if performed and all(s.ok for s in performed):
                            trace.goal_reached = True
                            trace.success = True
                            break
                        failed = "; ".join(s.detail for s in trace.steps if not s.ok) or "no actions performed"
                        history.append(f"[done] no assertions and {failed}")
                        if done_attempts > self.assertion_retries:
                            trace.error = trace.error or f"no assertions provided and goal unverified: {failed}"
                            break
                        continue
                    failed = "; ".join(r.detail for r in results if not r.passed)
                    history.append(f"[done] assertions failed: {failed}")
                    if done_attempts > self.assertion_retries:
                        trace.error = trace.error or f"assertions not met after {done_attempts} attempts: {failed}"
                        break
                    continue

                if action == "fail":
                    trace.error = thought or "agent declared failure"
                    break

                step_no += 1
                ok, detail = self._execute_action(action, target, kind, value)
                step = ActionTrace(
                    step=step_no,
                    action=action,
                    target=target,
                    kind=kind,
                    value=value,
                    ok=ok,
                    thought=thought,
                    detail=detail,
                    url=current_url,
                    interactive_elements=interactive[:40],
                    duration_ms=0.0,
                    timestamp=time.time(),
                )
                trace.steps.append(step)
                history.append(f"[{action}] {target} -> {'ok' if ok else 'FAIL: ' + detail}")
                if not ok:
                    logger.warning("agentic action failed: %s", detail)
                    if not trace.error:
                        trace.error = f"{action} on '{target}' failed: {detail}"
                    consecutive_failures += 1
                    # Locator/resolve errors can't be fixed by more guessing this
                    # run -- abort fast so the specific error reaches the heal loop.
                    if _is_locator_error(detail) or consecutive_failures >= max_consecutive_failures:
                        trace.error = trace.error or f"{action} on '{target}' failed: {detail}"
                        break
                else:
                    consecutive_failures = 0

            if step_no >= self.max_turns and not trace.success:
                trace.error = trace.error or f"exceeded max_turns ({self.max_turns}) without reaching goal"
        finally:
            try:
                trace.final_url = bt.browser_get_url().get("url", "") if snap.get("ok") else ""
            except Exception:  # noqa: BLE001
                pass
            bt.browser_stop()
            trace.total_duration_ms = (time.time() - start_ts) * 1000.0

        emitter.emit(
            EV_DONE,
            success=trace.success,
            goal_reached=trace.goal_reached,
            final_node="agentic",
            error=trace.error,
        )

        # Generate static Playwright test from successful trace
        generated_code = None
        successful_steps = [s for s in trace.steps if s.ok and s.action not in ("done", "fail")]
        if successful_steps:
            from .trace_to_code import trace_to_code_refined
            try:
                generated_code = trace_to_code_refined(
                    trace,
                    llm_infer_fn=self.llm.infer,
                )
                logger.info("generated %d-char refined test code from %d steps", len(generated_code), len(successful_steps))
                emitter.emit(EV_THINKING, node_id="agentic", text=f"[generated test code: {len(generated_code)} chars]")
            except Exception:  # noqa: BLE001
                logger.debug("failed to generate refined code, falling back to raw", exc_info=True)
                from .trace_to_code import trace_to_code
                try:
                    generated_code = trace_to_code(trace)
                except Exception:  # noqa: BLE001
                    pass

        return AgenticResult(trace.success, trace.goal_reached, trace, trace.error, generated_code=generated_code)

    # ------------------------------------------------------------------ #
    def _plan_batch(
        self,
        goal: str,
        assertions: list[dict[str, Any]],
        url: str,
        interactive: list[dict[str, Any]],
        constraints: dict[str, Any],
    ) -> Optional[list[dict]]:
        """One LLM call that returns the full action sequence. Returns None to
        fall back to step-by-step planning."""
        assertion_lines = "\n".join(
            f"- {a.get('description', a.get('type', ''))} "
            f"(type={a.get('type')}, target={a.get('target','')}, "
            f"expected={a.get('expected','')}, pattern={a.get('pattern','')})"
            for a in assertions
        ) or "(none)"
        def _fmt_batch_elem(e: dict) -> str:
            s = f"- {e.get('role')}|{e.get('name')}"
            ctx = e.get("context")
            if ctx:
                s += f" (context: {ctx})"
            return s
        elem_lines = "\n".join(_fmt_batch_elem(e) for e in interactive[:60]) or "(no interactive elements)"

        prompt = (
            f"{_BATCH_PLAN_SYSTEM}\n\n"
            f"GOAL: {goal}\n"
            f"ASSERTIONS TO VERIFY AFTER COMPLETION:\n{assertion_lines}\n\n"
            f"CURRENT URL: {url}\n"
            f"VISIBLE INTERACTIVE ELEMENTS:\n{elem_lines}\n\n"
            f"Plan the complete action sequence as JSON.\n\n"
            f"CRITICAL: Respond with ONLY a single JSON object with an 'actions' array."
        )
        llm_name, out = self.llm.infer(prompt, max_tokens=4096, temperature=0.0)
        if not out:
            logger.warning("batch planner: no LLM response")
            return None
        logger.info("batch planner raw output (%d chars): %s", len(out), out[:500])
        batch = _extract_batch(out)
        if not batch:
            logger.warning("batch planner: no parseable actions (raw=%s)", out[:2000])
            return None
        logger.info("batch plan: %d actions", len(batch))
        return batch

    # ------------------------------------------------------------------ #
    def _plan(
        self,
        goal: str,
        assertions: list[dict[str, Any]],
        url: str,
        interactive: list[dict[str, Any]],
        history: list[str],
        constraints: dict[str, Any],
    ) -> dict[str, Any]:
        assertion_lines = "\n".join(
            f"- {a.get('description', a.get('type', ''))} "
            f"(type={a.get('type')}, target={a.get('target','')}, "
            f"expected={a.get('expected','')}, pattern={a.get('pattern','')})"
            for a in assertions
        ) or "(none -- judge goal reached by observed state)"
        def _fmt_step_elem(e: dict) -> str:
            s = f"- {e.get('role')}|{e.get('name')}"
            ctx = e.get("context")
            if ctx:
                s += f" (context: {ctx})"
            return s
        elem_lines = "\n".join(_fmt_step_elem(e) for e in interactive[:60]) or "(no interactive elements)"
        hist_lines = "\n".join(history[-12:]) or "(no actions yet)"

        prompt = (
            f"{_PLANNER_SYSTEM}\n\n"
            f"GOAL: {goal}\n"
            f"ASSERTIONS TO VERIFY WHEN DONE:\n{assertion_lines}\n\n"
            f"CURRENT URL: {url}\n"
            f"VISIBLE INTERACTIVE ELEMENTS:\n{elem_lines}\n\n"
            f"PREVIOUS ACTIONS (most recent last):\n{hist_lines}\n\n"
            f"Decide the next action as JSON.\n\n"
            f"CRITICAL: Respond with ONLY a single JSON object, starting with '{{' "
            f"and ending with '}}'. No prose, no markdown fences, no explanation "
            f"before or after the JSON."
        )
        # Retry with an even firmer instruction if the model emits prose
        # instead of a JSON object (reasoning models sometimes echo the prompt).
        # The planner only needs a small JSON object, so keep the token budget
        # tiny -- a large max_tokens is the dominant source of per-turn latency.
        attempts = [
            prompt,
            prompt + "\n\nI repeat: output NOTHING except the JSON object. Your entire response must be valid JSON beginning with '{' and ending with '}'.",
        ]
        for attempt_no, p in enumerate(attempts):
            llm_name, out = self.llm.infer(p, max_tokens=2048, temperature=0.0)
            if not out:
                reason = ""
                if hasattr(self.llm, "get_last_error"):
                    reason = self.llm.get_last_error() or ""
                if attempt_no == len(attempts) - 1:
                    thought = f"no LLM response available; {reason}" if reason else "no LLM response available"
                    return {"action": "fail", "thought": thought}
                continue
            parsed = _extract_json(out)
            if parsed:
                parsed.setdefault("action", "fail")
                return parsed
            # Fallback: try to extract an action from prose output
            prose_action = _extract_action_from_prose(out)
            if prose_action:
                logger.info("extracted action from prose: %s", prose_action)
                return prose_action
            logger.warning("planner returned non-JSON (attempt %d): %s", attempt_no + 1, out[:200])
        return {"action": "fail", "thought": "planner produced no parseable JSON"}

    def _execute_action(self, action: str, target: str, kind: str, value: str) -> tuple[bool, str]:
        self.emitter.emit(EV_TOOL_CALL, name=f"browser_{action}", arguments={"target": target, "kind": kind, "value": value})
        try:
            if action == "navigate":
                res = bt.browser_navigate(target)
            elif action == "click":
                res = bt.browser_click(target, kind)
            elif action == "type":
                res = bt.browser_type(target, value, kind)
            elif action == "select":
                res = bt.browser_select(target, value, kind)
            elif action == "wait":
                res = bt.browser_wait_for(target, kind)
            elif action == "assert_visible":
                res = bt.browser_assert_visible(target, kind)
            elif action == "assert_text":
                res = bt.browser_assert_text(target, value, kind)
            elif action == "assert_url":
                res = bt.browser_assert_url(value)
            else:
                return False, f"unsupported action {action}"
        except Exception as exc:  # noqa: BLE001
            self.emitter.emit(EV_TOOL_RESULT, name=f"browser_{action}", ok=False, error=str(exc))
            return False, str(exc)
        ok = bool(res.get("ok"))
        detail = res.get("error") or ("ok" if ok else "action returned ok=false")
        self.emitter.emit(EV_TOOL_RESULT, name=f"browser_{action}", ok=ok, result=str(res)[:200])
        return ok, detail

    def _verify_assertions(self, assertions: list[dict[str, Any]]) -> list[AssertionResult]:
        """Verify assertions. Uses the LLM to judge free-form / ambiguous
        assertions against live page state, falling back to mechanical
        checks (visibility / text / url) when the LLM is unavailable or
        returns no verdict for a given assertion."""
        snap = bt.browser_snapshot()
        url = bt.browser_get_url().get("url", "")
        llm_results = self._judge_assertions_llm(assertions, snap, url)
        results: list[AssertionResult] = []
        for i, a in enumerate(assertions):
            atype = a.get("type", "visibility")
            desc = a.get("description", atype)
            if llm_results is not None and i < len(llm_results) and llm_results[i] is not None:
                results.append(llm_results[i])
                continue
            # Mechanical fallback
            try:
                if atype == "visibility":
                    res = bt.browser_assert_visible(a.get("target", ""), a.get("kind", "auto"))
                    passed = bool(res.get("ok"))
                    detail = "" if passed else (res.get("error") or f"not visible: {a.get('target')}")
                elif atype == "text":
                    res = bt.browser_assert_text(a.get("expected", ""), a.get("target", ""), a.get("kind", "auto"))
                    passed = bool(res.get("ok"))
                    detail = "" if passed else f"text not found: {a.get('expected')}"
                elif atype == "url":
                    res = bt.browser_assert_url(a.get("pattern", ""))
                    passed = bool(res.get("ok"))
                    detail = "" if passed else f"url mismatch: {res.get('url')}"
                else:
                    passed = False
                    detail = f"unknown assertion type {atype}"
            except Exception as exc:  # noqa: BLE001
                passed = False
                detail = str(exc)
            results.append(AssertionResult(type=atype, description=desc, passed=passed, detail=detail))
        return results

    def _judge_assertions_llm(
        self, assertions: list[dict[str, Any]], snap: dict[str, Any], url: str
    ) -> Optional[list[Optional[AssertionResult]]]:
        """Ask the LLM to judge each assertion against the live page state.

        Returns a list parallel to ``assertions``; entries are either an
        AssertionResult or None (when the LLM gave no verdict, so the caller
        should fall back to mechanical checks). Returns None entirely if the
        LLM is unavailable."""
        if not assertions:
            return None

        els = snap.get("interactive_elements", []) if isinstance(snap, dict) else []
        el_lines = (
            "\n".join(f"- {e.get('role')}|{e.get('name')}" for e in els[:60]) or "(none)"
        )
        tree = snap.get("accessibility_tree", "") if isinstance(snap, dict) else ""
        tree_text = (tree if isinstance(tree, str) else "")[:2000]

        asserts_txt = "\n".join(
            f"{i}. [{a.get('type', '?')}] "
            f"{a.get('expected') or a.get('target') or a.get('pattern') or ''}"
            for i, a in enumerate(assertions)
        )
        prompt = (
            "You are a strict test assertion judge. Given the current page "
            "state and a list of assertions, decide for EACH assertion whether "
            "it PASSES or FAILS. Only pass when the evidence clearly supports it.\n\n"
            f"CURRENT URL: {url}\n\n"
            f"VISIBLE PAGE TEXT (truncated):\n{tree_text}\n\n"
            f"INTERACTIVE ELEMENTS:\n{el_lines}\n\n"
            "ASSERTIONS TO JUDGE:\n"
            f"{asserts_txt}\n\n"
            "Respond with ONLY a JSON array, one object per assertion in order:\n"
            '[{"index":0,"passed":true,"reason":"..."},'
            '{"index":1,"passed":false,"reason":"..."}]\n'
        )
        try:
            _name, out = self.llm.infer(prompt, max_tokens=1024, temperature=0.0)
        except Exception:  # noqa: BLE001
            return None
        if not out:
            return None
        arr = _extract_json_array(out)
        if not isinstance(arr, list):
            return None

        results: list[Optional[AssertionResult]] = []
        for i, a in enumerate(assertions):
            atype = a.get("type", "visibility")
            desc = a.get("description", atype)
            match = next((x for x in arr if x.get("index") == i), None)
            if match and isinstance(match.get("passed"), bool):
                results.append(
                    AssertionResult(
                        type=atype,
                        description=desc,
                        passed=match["passed"],
                        detail=match.get("reason", ""),
                    )
                )
            else:
                results.append(None)
        return results
