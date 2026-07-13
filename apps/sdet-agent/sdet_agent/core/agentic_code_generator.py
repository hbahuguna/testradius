"""Agent-driven test generation with multi-page exploration (Slack-style).

Adopts the Slack "Agent + Playwright MCP" approach: instead of requiring the
user to manually record UI actions, the agent explores the live page through
Playwright MCP (accessibility snapshots + browser actions), then generates
deterministic Playwright test code from those observations.

Flow:
    goal + url
      -> [explore] navigate, snapshot, click/type/select, repeat (multi-page)
      -> [generate] LLM writes Playwright code from all observations
      -> [verify+heal] handled by the caller's run-spec / heal loop

Because the agent reads the live accessibility tree, locators are correct from
the start (e.g. ``getByLabel('Applying For')`` instead of guessing from option
text), eliminating the recorder round-trip that produced wrong selectors.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..core.events import EV_DONE, EV_ERROR, EV_NODE, EV_THINKING, EV_TOOL_CALL, EV_TOOL_RESULT, _NoopEmitter
from ..tools import browser_tools as bt
from ..reasoning.llm_factory import LLMFactory, LLMClientConfig
from ..reasoning.hy3_client import Hy3Client
from ..reasoning.qwen_client import QwenClient

logger = logging.getLogger("sdet_agent.codegen")

_EXPLORE_SYSTEM = (
    "You are an expert SDET explorer. You are given a TEST GOAL and the live "
    "state of a web page (an accessibility snapshot + URL). Your job is to "
    "EXPLORE the page so that you can later generate a Playwright test that "
    "achieves the goal.\n\n"
    "PREFER ACCESSIBLE LOCATORS. The VISIBLE INTERACTIVE ELEMENTS list uses the "
    "exact format 'role|name' (e.g. 'button|Join Pilot', 'combobox|role', "
    "'textbox|First name', 'link|View PDF'). To click or fill an element, copy "
    "that exact 'role|name' string as the target and set kind='role'. For "
    "buttons/links addressed by their visible text, you may instead use "
    "kind='text' with the visible text as target. Avoid CSS ids/classes.\n\n"
    "Decide the SINGLE next exploration action. You may:\n"
    "- navigate to a URL (use this to reach a starting page for the flow)\n"
    "- click / type / select an element to see what the page does next\n"
    "- wait for an element to appear\n"
    "- assert_visible / assert_text to confirm an element is present\n"
    "- done -- you have explored enough and are ready to generate the test\n\n"
    "Respond with ONLY a JSON object, no prose, no code fences. For example:\n"
    "{\n"
    '  "thought": "Navigate to the login page first.",\n'
    '  "action": "navigate",\n'
    '  "target": "https://example.com/login",\n'
    '  "kind": "auto",\n'
    '  "value": "",\n'
    '  "confidence": 0.9\n'
    "}\n\n"
    "Rules:\n"
    "- Explore enough to understand the full flow the test must cover, but do "
    "NOT try to complete the goal -- just observe. Stop with action='done' once "
    "you have seen every page/state the test will need to interact with.\n"
    "- Prefer exploring the happy path the test will assert.\n"
    "- Keep exploration focused; 3-8 steps is usually enough.\n"
)

_GENERATE_SYSTEM = (
    "You are an expert SDET engineer. Write a PRODUCTION-GRADE, COMPLETE "
    "Playwright test in TypeScript that fully achieves the stated GOAL against "
    "the page(s) explored.\n\n"
    "Locator rules (CRITICAL -- follow exactly):\n"
    "- Use accessible locators first: getByRole, getByLabel, getByPlaceholder, "
    "getByText, getByAltText. Prefer getByLabel for form fields.\n"
    "- Use the EXACT 'role|name' strings observed in the page snapshots. For a "
    "combobox/select named 'Applying For', write page.getByLabel('Applying For'). "
    "For a textbox named 'First Name', write page.getByLabel('First Name'). "
    "Do NOT invent names; use what the snapshot reported.\n"
    "- Only use CSS (#id / .class) as a last resort.\n\n"
    "COMPLETENESS (CRITICAL):\n"
    "- For EVERY interactive element the goal touches, emit a step. If the goal "
    "says fill first name, last name, email -> fill all three. Do not stop after "
    "the first field.\n"
    "- For select/combobox use .selectOption({ label: '...' }) with a REAL "
    "option, never the placeholder. The first option is almost always a "
    "placeholder like 'Select a role...'; pick the second or third option.\n"
    "- Always finish the flow: click the submit/primary button, then assert the "
    "expected success state. Common patterns after form submission:\n"
    "  * A confirmation heading: page.getByRole('heading', { name: /success|received|thank/i })\n"
    "  * A success toast or banner: page.getByText(/submitted|success/i)\n"
    "  * URL redirect: expect(page).toHaveURL(/thank|success/i)\n"
    "- Never assert the submit button disappears -- most SPAs keep it in DOM.\n"
    "- If the success state is unknown from observations, assert the submit "
    "button exists and no error is visible; never omit the submit step.\n\n"
    "STYLE (CRITICAL):\n"
    "- Keep tests SHORT and FOCUSED. No try/catch, no console monitoring, "
    "no multiple fallback indicators. One clear assertion per step.\n"
    "- Use await expect(locator).toBeVisible() before interacting with an element.\n"
    "- Use await expect(locator).toHaveValue() after filling to verify.\n"
    "- Do NOT wrap assertions in try/catch -- let Playwright fail naturally.\n"
    "Test structure:\n"
    "- Import { test, expect } from '@playwright/test'.\n"
    "- Use realistic test data (realistic names/emails/URLs), never 'test'/'foo'.\n"
    "- Assert at every step: visibility, value, URL. Use waitFor / toBeVisible "
    "for async state; avoid fixed timeouts.\n"
    "- If a repo already has page objects for this app, REUSE them (import + "
    "call) instead of duplicating locators.\n"
    "- Treat wording literally: 'Link to Resume' is a URL/text link, NOT a file "
    "upload (use fill, not setInputFiles) unless an upload is explicitly requested.\n"
    "- Output ONLY valid TypeScript inside a single ```typescript fenced block. "
    "No explanation outside the block.\n"
)


@dataclass
class Observation:
    """A single page snapshot captured during exploration."""
    url: str
    interactive_elements: list[dict[str, Any]]
    page_text: str = ""
    action_taken: Optional[str] = None  # description of what led here


@dataclass
class GenerateResult:
    success: bool
    code: str = ""
    observations: list[Observation] = field(default_factory=list)
    exploration_log: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "generated_code": self.code,
            "observations": [
                {
                    "url": o.url,
                    "action_taken": o.action_taken,
                    "interactive_elements": o.interactive_elements[:60],
                    "page_text": (o.page_text or "")[:1500],
                }
                for o in self.observations
            ],
            "exploration_log": self.exploration_log,
            "error": self.error,
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
    last = text.rfind("}")
    if start != -1 and last > start:
        chunk = text[start : last + 1]
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            pass
    return None


def _extract_code(text: str) -> str:
    """Extract the ```typescript fenced block (or first code block) from LLM text."""
    if not text:
        return ""
    m = re.search(r"```(?:typescript|ts|js|javascript)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Fallback: if no fence, return the raw text trimmed.
    return text.strip()


class AgenticCodeGenerator:
    """Explores a live page via Playwright MCP, then generates test code."""

    def __init__(
        self,
        llm_factory: Optional[LLMFactory] = None,
        emitter=None,
        max_explore_turns: int = 8,
        backend: str = "mcp",
        headless: bool = True,
    ):
        self.llm = llm_factory or _default_factory()
        self.emitter = emitter or _NoopEmitter()
        self.max_explore_turns = max_explore_turns
        self.backend = backend
        self.headless = headless

    # ------------------------------------------------------------------ #
    def generate(
        self,
        goal: str,
        url: str,
        repo_dir: str = "",
        starting_url: Optional[str] = None,
    ) -> GenerateResult:
        """Explore ``url`` (or ``starting_url``) then generate a Playwright test.

        ``starting_url`` lets the caller send the agent to a landing page first
        (e.g. the careers page) before it navigates to the form under test.
        """
        emitter = self.emitter
        emitter.emit(EV_NODE, node_id="codegen", role="agent", name="agentic-codegen")
        observations: list[Observation] = []
        exploration_log: list[str] = []
        start_ts = time.time()

        start = bt.browser_start(headless=self.headless, backend=self.backend)
        if start.get("status") == "error":
            err = start.get("error", "browser start failed")
            emitter.emit(EV_ERROR, message=err)
            return GenerateResult(False, error=err)

        entry = starting_url or url
        bt.browser_navigate(entry)
        try:
            history: list[str] = []
            step_no = 0
            while step_no < self.max_explore_turns:
                snap = bt.browser_snapshot()
                if not snap.get("ok"):
                    exploration_log.append("[snapshot] failed; stopping exploration")
                    break
                interactive = snap.get("interactive_elements", [])
                current_url = snap.get("url", entry)
                obs = Observation(
                    url=current_url,
                    interactive_elements=interactive,
                    page_text=str(snap.get("accessibility_tree") or snap.get("page_text") or "")[:4000],
                    action_taken=history[-1] if history else None,
                )
                observations.append(obs)

                plan = self._plan_explore(goal, observations, history)
                action = plan.get("action", "done")
                if action not in ("navigate", "click", "type", "select", "wait",
                                  "assert_visible", "assert_text", "done"):
                    action = "done"
                thought = plan.get("thought", "")

                if action == "done":
                    emitter.emit(EV_THINKING, node_id="codegen", text="exploration complete")
                    break

                target = plan.get("target", "")
                kind = plan.get("kind", "auto")
                value = plan.get("value", "")
                emitter.emit(EV_THINKING, node_id="codegen", text=thought)

                ok, detail = self._execute(action, target, kind, value)
                step_no += 1
                log_line = f"[{action}] {target}{(' = ' + value) if value else ''} -> {'ok' if ok else 'FAIL: ' + detail}"
                history.append(log_line)
                exploration_log.append(log_line)
                if not ok:
                    logger.warning("exploration action failed: %s", detail)

            # Generate the test from everything observed. Retry once if the
            # first pass looks incomplete (missing navigation or a submit step).
            emitter.emit(EV_THINKING, node_id="codegen", text="generating Playwright test from observations")
            code = self._generate_code(goal, url, observations, repo_dir)
            if code and not self._looks_complete(code):
                exploration_log.append("[generate] first pass incomplete; regenerating with stronger nudge")
                code = self._generate_code(goal, url, observations, repo_dir,
                                           nudge="The previous attempt was INCOMPLETE: it was missing "
                                                 "page.goto, one or more field fills, the submit click, or the "
                                                 "success assertion. Write the FULL end-to-end test now.")
            if not code:
                err = "LLM produced no usable test code"
                emitter.emit(EV_ERROR, message=err)
                return GenerateResult(False, observations=observations,
                                      exploration_log=exploration_log, error=err)

            emitter.emit(EV_DONE, success=True, final_node="codegen", generated_code=code)
            return GenerateResult(
                True, code=code, observations=observations, exploration_log=exploration_log
            )
        finally:
            bt.browser_stop()
            logger.info("codegen took %.1fs", time.time() - start_ts)

    # ------------------------------------------------------------------ #
    def _plan_explore(
        self,
        goal: str,
        observations: list[Observation],
        history: list[str],
    ) -> dict[str, Any]:
        elem_lines = "\n".join(
            f"- {e.get('role')}|{e.get('name')}" for e in observations[-1].interactive_elements[:60]
        ) if observations else "(no elements)"
        hist_lines = "\n".join(history[-12:]) or "(no actions yet)"
        current_url = observations[-1].url if observations else "(unknown)"

        prompt = (
            f"{_EXPLORE_SYSTEM}\n\n"
            f"TEST GOAL: {goal}\n\n"
            f"CURRENT URL: {current_url}\n"
            f"VISIBLE INTERACTIVE ELEMENTS:\n{elem_lines}\n\n"
            f"PREVIOUS EXPLORATION STEPS:\n{hist_lines}\n\n"
            f"Decide the next exploration action as JSON.\n\n"
            f"CRITICAL: Respond with ONLY a single JSON object, starting with '{{' "
            f"and ending with '}}'. No prose, no markdown fences."
        )
        attempts = [
            prompt,
            prompt + "\n\nI repeat: output NOTHING except the JSON object. Your entire response must be valid JSON beginning with '{' and ending with '}'.",
        ]
        for attempt_no, p in enumerate(attempts):
            _, out = self.llm.infer(p, max_tokens=2048, temperature=0.0)
            logger.info("[explore-planner] raw out (attempt %d):\n%s", attempt_no + 1, (out or "")[:1500])
            if not out:
                continue
            parsed = _extract_json(out)
            if parsed:
                parsed.setdefault("action", "done")
                return parsed
            logger.warning("explore planner returned non-JSON (attempt %d): %s", attempt_no + 1, out[:200])
        return {"action": "done", "thought": "planner produced no parseable JSON; stopping exploration"}

    def _execute(self, action: str, target: str, kind: str, value: str) -> tuple[bool, str]:
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
                res = bt.browser_assert_text(value, target, kind)
            else:
                return False, f"unsupported action {action}"
        except Exception as exc:  # noqa: BLE001
            self.emitter.emit(EV_TOOL_RESULT, name=f"browser_{action}", ok=False, error=str(exc))
            return False, str(exc)
        ok = bool(res.get("ok"))
        detail = res.get("error") or ("ok" if ok else "action returned ok=false")
        self.emitter.emit(EV_TOOL_RESULT, name=f"browser_{action}", ok=ok, result=str(res)[:200])
        return ok, detail

    @staticmethod
    def _looks_complete(code: str) -> bool:
        """Heuristic: a usable end-to-end test must navigate and act."""
        if not code:
            return False
        c = code.lower()
        has_goto = "goto(" in c
        has_action = ("click(" in c) or ("fill(" in c) or ("selectoption(" in c)
        has_assert = "expect(" in c
        return has_goto and has_action and has_assert

    def _generate_code(
        self,
        goal: str,
        url: str,
        observations: list[Observation],
        repo_dir: str,
        nudge: str = "",
    ) -> str:
        # Build a compact but complete picture of every page explored.
        pages_block = ""
        for i, obs in enumerate(observations, 1):
            elems = "\n".join(
                f"      - {e.get('role')}|{e.get('name')}" for e in obs.interactive_elements[:60]
            ) or "      (none)"
            step_desc = obs.action_taken or ("initial page" if i == 1 else "after previous step")
            pages_block += (
                f"\n  Page {i} (reached by: {step_desc})\n"
                f"    URL: {obs.url}\n"
                f"    Interactive elements:\n{elems}\n"
            )

        repo_hint = ""
        if repo_dir:
            repo_hint = (
                f"\nThe automation repo is at: {repo_dir}. If it already contains "
                f"page objects for this app, REUSE them (import + call).\n"
            )

        nudge_block = f"\nIMPORTANT REMINDER: {nudge}\n" if nudge else ""
        prompt = (
            f"{_GENERATE_SYSTEM}\n\n"
            f"TEST GOAL:\n{goal}\n\n"
            f"PRIMARY URL (page.goto target):\n{url}\n"
            f"{repo_hint}\n"
            f"PAGES EXPLORED (use the exact role|name strings below):"
            f"{pages_block}\n"
            f"{nudge_block}\n"
            f"Write the complete Playwright test now.\n"
        )
        _, out = self.llm.infer(prompt, max_tokens=4096, temperature=0.0)
        logger.info("[generate-code] raw out:\n%s", (out or "")[:2500])
        code = _extract_code(out)
        # Defensive: if the model wrapped the code oddly, re-extract from raw.
        if not code and out:
            code = _extract_code(out)
        return code
