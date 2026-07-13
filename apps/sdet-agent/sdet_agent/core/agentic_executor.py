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
    "Prefer accessible locators: role|name (e.g. 'button|Submit Application'), "
    "label, text, or placeholder. Avoid CSS ids/classes unless nothing else "
    "works.\n\n"
    "Respond with ONLY a JSON object, no prose, no code fences:\n"
    "{\n"
    '  "thought": "one-line rationale for this action",\n'
    '  "action": "navigate|click|type|select|wait|assert_visible|assert_text|assert_url|done|fail",\n'
    '  "target": "accessible locator target or URL or expected text",\n'
    '  "kind": "auto|role|label|text|placeholder|css",\n'
    '  "value": "text to type / option to select / url pattern (omit otherwise)",\n'
    '  "confidence": 0.0\n'
    "}\n\n"
    "Rules:\n"
    "- Use 'done' ONLY when the goal is fully achieved and key steps are done.\n"
    "- Use 'fail' if you cannot make progress after retrying.\n"
    "- 'assert_text': target = expected substring; value = optional scoping locator.\n"
    "- 'assert_url': value = regex pattern the current URL must match.\n"
)

_VALID_ACTIONS = {
    "navigate", "click", "type", "select", "wait",
    "assert_visible", "assert_text", "assert_url", "done", "fail",
}


@dataclass
class AgenticResult:
    success: bool
    goal_reached: bool
    trace: ExecutionTrace
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "goal_reached": self.goal_reached,
            "error": self.error,
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


class AgenticExecutor:
    """Runs a goal-driven agentic test against a live browser."""

    def __init__(
        self,
        llm_factory: Optional[LLMFactory] = None,
        emitter=None,
        max_turns: int = 30,
        backend: str = "mcp",
        headless: bool = True,
        assertion_retries: int = 3,
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
        snap: dict[str, Any] = {"ok": False}

        try:
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
                if action not in _VALID_ACTIONS:
                    action = "fail"
                    plan["thought"] = f"invalid action from planner: {action}"

                verdict = check_action_allowed(action, constraints)
                if not verdict.allow and action not in ("done", "fail"):
                    action = "fail"
                    plan["thought"] = verdict.reason

                target = plan.get("target", "")
                kind = plan.get("kind", "auto")
                value = plan.get("value", "")
                thought = plan.get("thought", "")

                emitter.emit(EV_THINKING, node_id="agentic", text=thought)

                if action == "done":
                    done_attempts += 1
                    results = self._verify_assertions(assertions)
                    trace.assertions.extend(results)
                    if all(r.passed for r in results):
                        trace.goal_reached = True
                        trace.success = True
                        break
                    failed = "; ".join(r.detail for r in results if not r.passed)
                    history.append(f"[done] assertions failed: {failed}")
                    if done_attempts > self.assertion_retries:
                        trace.error = f"assertions not met after {done_attempts} attempts: {failed}"
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
                    url=current_url,
                    interactive_elements=interactive[:40],
                    duration_ms=0.0,
                    timestamp=time.time(),
                )
                trace.steps.append(step)
                history.append(f"[{action}] {target} -> {'ok' if ok else 'FAIL: ' + detail}")
                if not ok:
                    logger.warning("agentic action failed: %s", detail)

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
        return AgenticResult(trace.success, trace.goal_reached, trace, trace.error)

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
        elem_lines = "\n".join(f"- {e.get('role')}|{e.get('name')}" for e in interactive[:60]) or "(no interactive elements)"
        hist_lines = "\n".join(history[-12:]) or "(no actions yet)"

        prompt = (
            f"{_PLANNER_SYSTEM}\n\n"
            f"GOAL: {goal}\n"
            f"ASSERTIONS TO VERIFY WHEN DONE:\n{assertion_lines}\n\n"
            f"CURRENT URL: {url}\n"
            f"VISIBLE INTERACTIVE ELEMENTS:\n{elem_lines}\n\n"
            f"PREVIOUS ACTIONS (most recent last):\n{hist_lines}\n\n"
            f"Decide the next action as JSON."
        )
        # Retry once with a firmer instruction if the model emits prose instead
        # of a JSON object (reasoning models sometimes echo the prompt back).
        attempts = [
            prompt,
            prompt + "\n\nCRITICAL: Respond with ONLY a single JSON object, starting with '{' and ending with '}'. No prose, no markdown fences, no explanation.",
        ]
        for attempt_no, p in enumerate(attempts):
            llm_name, out = self.llm.infer(p, max_tokens=1024, temperature=0.0)
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
        results: list[AssertionResult] = []
        for a in assertions:
            atype = a.get("type", "visibility")
            desc = a.get("description", atype)
            try:
                if atype == "visibility":
                    res = bt.browser_assert_visible(a.get("target", ""), a.get("kind", "auto"))
                    passed = bool(res.get("ok"))
                    detail = "" if passed else f"not visible: {a.get('target')}"
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
