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

# Maximum autonomous self-heal attempts for a single failing action. When an
# action fails with a locator error (e.g. "no element matched"), the executor
# feeds the failure back as live context, re-snapshots the page, and asks the
# planner to pick a corrected locator — without any human intervention — up to
# this many times before giving up on that action.
MAX_LOCATOR_RETRIES = 10

# Substrings that indicate a locator/element-resolution problem (as opposed to a
# genuine "the page is broken" failure). Only these trigger the self-heal loop.
_LOCATOR_ERROR_HINTS = (
    "no element matched", "no element found", "ambiguous",
    "strict mode violation", "element is not", "timeout",
    "unable to locate", "locator", "not found",
)

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
from ..reasoning.byok_client import ByokAuthError, ByokError

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
    '  "thought": "Click the primary call-to-action to continue",\n'
    '  "action": "click",\n'
    '  "target": "button|Example CTA",\n'
    '  "kind": "role",\n'
    '  "value": "",\n'
    '  "confidence": 0.9\n'
    "}\n\n"
    "NOTE: The example above shows ONLY the JSON FORMAT. Never click "
    "'button|Example CTA' or any other element from the example — only "
    "interact with elements that actually appear in the VISIBLE "
    "INTERACTIVE ELEMENTS list for the current page.\n\n"
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
    "- Do NOT repeat a step you have already performed successfully (e.g. do not "
    "re-click the same menu/item after it already navigated). Once the goal's "
    "final interaction is complete and the expected page is shown, emit 'done'.\n"
    "- 'toggle' in the GOAL means a switch/checkbox element — look for switch or checkbox role, then click it.\n"
    "- 'assert_text': target = expected substring; value = optional scoping locator.\n"
    "- 'assert_url': value = regex pattern the current URL must match.\n"
    "- 'screenshot': optional observation step that captures a frame of the "
    "current page. It never changes page state and is always allowed; use it "
    "only if the goal explicitly asks to capture the screen.\n"
)

_VALID_ACTIONS = {
    "navigate", "click", "type", "select", "wait", "scroll", "screenshot",
    "assert_visible", "assert_text", "assert_url", "done", "fail",
}

_ACTION_ALIASES = {
    "fill": "type", "enter": "type", "input": "type", "write": "type",
    "choose": "select", "pick": "select",
    "open": "navigate", "goto": "navigate", "go_to": "navigate",
    "verify": "assert_visible", "check": "assert_visible", "assert": "assert_visible",
    "capture": "screenshot", "snapshot": "screenshot",
    "finish": "done", "complete": "done", "stop": "done",
}

# Locator/resolve errors cannot self-heal within a single run -- the planner
# needs the self-healer to rewrite the spec. Abort fast so the error feeds the
# heal loop instead of burning turns.
_LOCATOR_ERROR_HINTS = ("no element matched", "ambiguous", "strict mode violation", "element is not")

# User-initiated cancellation. A single in-flight agentic run is supported at a
# time (worker-thread model), so a module-level flag is sufficient. The HTTP
# layer sets it via ``request_agentic_stop()``; the run loop checks
# ``is_agentic_stopped()`` after every step and bails out immediately.
_AGENTIC_STOP_REQUESTED = {"flag": False}


def request_agentic_stop() -> None:
    """Signal the currently-running agentic run to stop as soon as possible."""
    _AGENTIC_STOP_REQUESTED["flag"] = True


def clear_agentic_stop() -> None:
    """Clear any pending stop request (call at the start of a new run)."""
    _AGENTIC_STOP_REQUESTED["flag"] = False


def is_agentic_stopped() -> bool:
    """True if a stop has been requested for the current run."""
    return _AGENTIC_STOP_REQUESTED["flag"]


def _is_locator_error(detail: str) -> bool:
    d = (detail or "").lower()
    return any(h in d for h in _LOCATOR_ERROR_HINTS)


def _normalize_step(action: str, target: str) -> str:
    """Normalize an action+target into a dedupe key (ignore value/kind)."""
    return f"{action}|{(target or '').strip().lower()}"


def _is_redundant_step(
    action: str,
    target: str,
    url: str,
    done_steps: list[tuple[str, str, str]],
) -> bool:
    """Return True if the planner is re-proposing a step it already performed
    successfully without advancing the page — i.e. the goal flow is complete
    and the agent is now looping/stalling.

    This is what stops a run that already reached the goal (e.g. navigated to
    the final page) from re-clicking the same elements and then spraying heal
    candidates on a junk target. Once we see a successful (action, target) we've
    already done, with no URL change since, we declare the goal reached.
    """
    key = _normalize_step(action, target)
    # Look at the most recent successful step with the same key.
    for a, t, u in reversed(done_steps):
        if _normalize_step(a, t) == key:
            # Redundant only if the page hasn't moved on to somewhere new.
            return u == url
    return False


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


def _byok_factory(byok: dict[str, str], model: Optional[str] = None) -> LLMFactory:
    """Build an LLMFactory that uses the user's own provider key.

    ``byok`` maps provider name -> api key, e.g. {"openai": "sk-..."} or
    {"anthropic": "sk-ant-..."}. The first present key wins. ``model`` is an
    optional explicit model id (e.g. "gpt-4o") overriding the provider default.
    """
    from ..reasoning.byok_client import ByokClient

    configs: list[LLMClientConfig] = []
    for provider in ("openai", "anthropic", "google", "opencode"):
        key = byok.get(provider)
        if not key:
            continue
        if provider == "opencode":
            from ..reasoning.hy3_client import Hy3Client

            configs.append(
                LLMClientConfig(
                    name="byok-opencode",
                    client_class=lambda api_url=None, k=key, m=model: Hy3Client(
                        api_key=k, api_url=api_url, model=m
                    ),
                )
            )
        else:
            configs.append(
                LLMClientConfig(
                    name=f"byok-{provider}",
                    client_class=lambda api_url=None, p=provider, k=key, m=model: ByokClient(
                        provider=p, api_key=k, api_url=api_url, model=m
                    ),
                )
            )
    if not configs:
        logger.warning("BYOK requested but no usable key supplied; falling back to default factory")
        return _default_factory()
    return LLMFactory(configs)


def _extract_json(text: str) -> Optional[dict]:
    """Pull the first balanced JSON object out of an LLM reply.

    Tries, in order: a strict balanced-scan, a first-'{'-to-last-'}' span, and
    a repair pass that tolerates common LLM JSON mistakes (trailing commas,
    unquoted keys, comments).
    """
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
        repaired = _repair_json(chunk)
        if repaired is not None:
            return repaired
    return None


def _repair_json(s: str) -> Optional[dict]:
    """Last-resort parse for LLM JSON that is *almost* valid.

    Handles trailing commas, // and /* */ comments, and unquoted object keys.
    (Single-quoted strings are intentionally NOT converted, since that risks
    corrupting apostrophes inside values; bad single-quote JSON simply fails
    here and the caller retries with a firmer prompt.)
    """
    if not s or "{" not in s:
        return None
    cleaned = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)
    cleaned = re.sub(r"(?<!:)//[^\n]*", "", cleaned)
    cleaned = re.sub(r",(\s*[\]}])", r"\1", cleaned)
    cleaned = re.sub(r'(?<![{\s":\[,])([A-Za-z_][A-Za-z0-9_]*)\s*:', r'"\1":', cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
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
    "format 'role|name' (e.g. 'button|Example CTA', 'combobox|role', "
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
    "- Maximum 20 actions.\n\n"
    "OUTPUT FORMAT (NON-NEGOTIABLE):\n"
    "Your entire response MUST be exactly one JSON object. Start with '{' and end "
    "with '}'. Do NOT write any prose, explanation, markdown, or code fences "
    "before or after the JSON. If you add any text outside the JSON object, the "
    "parser will fail and the run will be aborted, so output ONLY the JSON."
)


def _extract_batch(out: str) -> Optional[list[dict]]:
    """Extract an actions list from LLM output (single JSON or JSON-in-prose)."""
    if not out:
        return None
    parsed = _extract_json(out)
    if parsed:
        actions = parsed.get("actions")
        if isinstance(actions, list) and actions:
            return actions
        # Some models nest under "plan" or "steps".
        for key in ("plan", "steps", "sequence"):
            if isinstance(parsed.get(key), list) and parsed[key]:
                return parsed[key]
    # Fallback: extract the "actions" array directly from the raw text,
    # which works even when the surrounding object is malformed.
    m = re.search(r'"actions"\s*:\s*(\[.*?\])', out, flags=re.DOTALL)
    if m:
        try:
            arr = json.loads(m.group(1))
            if isinstance(arr, list) and arr:
                return arr
        except json.JSONDecodeError:
            pass
    # Also accept a bare top-level JSON array of actions.
    arr = _extract_json_array(out)
    if arr:
        return arr
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
        byok: Optional[dict[str, str]] = None,
        model: Optional[str] = None,
    ):
        if byok:
            self.llm = _byok_factory(byok, model=model)
            self._is_byok = True
        else:
            self.llm = llm_factory or _default_factory()
            self._is_byok = False
        self.emitter = emitter or _NoopEmitter()
        self.max_turns = max_turns
        self.backend = backend
        self.headless = headless
        self.assertion_retries = assertion_retries

    # ------------------------------------------------------------------ #
    def _streaming_infer(
        self, prompt: str, max_tokens: int = 1024, temperature: float = 0.3
    ) -> str:
        """LLM call that streams reasoning/answer tokens to the emitter as
        ``thinking_delta`` events (phase="codegen") and returns the assembled
        full text. Used for code generation so the Live Run feed shows the
        model's reasoning while the stored artifact is cleaned separately.
        """
        def on_delta(kind: str, text: str) -> None:
            if text:
                self.emitter.emit(EV_THINKING, node_id="agentic", text=text, phase="codegen")

        try:
            _name, full = self.llm.stream_infer(prompt, on_delta, max_tokens, temperature)
        except Exception:  # noqa: BLE001
            _name, full = None, ""
        return full or ""

    # ------------------------------------------------------------------ #
    def _validate_byok(self) -> None:
        """Cheaply prove the configured BYOK key works before the run starts.

        Performs one tiny streaming inference and lets any ByokAuthError /
        ByokError propagate to the caller (which aborts the run).
        """
        def _on_delta(kind: str, text: str) -> None:  # pragma: no cover - no-op
            pass

        is_anthropic = any(
            getattr(c, "provider", None) == "anthropic" for _n, c in self.llm.clients
        )
        probe = "ping" if is_anthropic else "Reply with the single word: OK"
        self.llm.stream_infer(probe, _on_delta, max_tokens=8, temperature=0.0)

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
        # Reset any stale stop request from a previous run.
        clear_agentic_stop()

        start_ts = time.time()
        emitter = self.emitter

        # Validate the BYOK key up front. A wrong/invalid provider key must fail
        # fast with a clear message — never silently fall back to a default
        # model (which would mask the misconfiguration and waste a credit).
        if self._is_byok:
            try:
                self._validate_byok()
            except (ByokAuthError, ByokError) as e:
                trace.error = str(e)
                emitter.emit(EV_ERROR, message=str(e))
                emitter.emit(
                    EV_DONE,
                    success=False,
                    trace=trace.to_dict(),
                    error=str(e),
                )
                return AgenticResult(False, False, trace, str(e))

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
        action_failed = False
        snap: dict[str, Any] = {"ok": False}
        # Successful (action, target, url) tuples, used to detect when the
        # planner re-proposes a step already completed (goal reached → stop).
        done_steps: list[tuple[str, str, str]] = []

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
                    # User pressed Stop — abort before executing the next step.
                    if is_agentic_stopped():
                        trace.error = trace.error or "stopped by user"
                        trace.stopped = True
                        emitter.emit(EV_ERROR, message="agentic run stopped by user")
                        break
                    act = ba.get("action", "fail")
                    act = _ACTION_ALIASES.get(act, act)
                    tgt = ba.get("target", "") or ba.get("element", "")
                    knd = ba.get("kind", "auto")
                    val = ba.get("value", "")
                    thought = ba.get("thought", "batch step")

                    emitter.emit(EV_THINKING, node_id="agentic", text=thought)

                    step_no += 1
                    ok, detail, gave_up, f_tgt, f_knd, f_val = self._execute_with_heal(
                        act, tgt, knd, val, current_url, interactive, history, constraints, goal,
                    )
                    step = ActionTrace(
                        step=step_no, action=act, target=f_tgt, kind=f_knd, value=f_val,
                        ok=ok, thought=thought, detail=detail, url=current_url,
                        interactive_elements=interactive[:40], duration_ms=0.0, timestamp=time.time(),
                    )
                    trace.steps.append(step)
                    history.append(f"[{act}] {f_tgt} -> {'ok' if ok else 'FAIL: ' + detail}")
                    if not ok:
                        logger.warning("batch action failed: %s", detail)
                        trace.error = trace.error or f"batch: {act} on '{f_tgt}' failed: {detail}"
                        action_failed = True
                        batch_ok = False
                        break
                    else:
                        post_url = bt.browser_get_url().get("url", current_url)
                        done_steps.append((act, f_tgt, post_url))

                if batch_ok:
                    # Wait for the page to settle and any success/confirmation
                    # message to render after a submit (these often appear a
                    # second or two later via a toast/redirect).
                    import time as _time
                    _time.sleep(4)
                    # All batch steps succeeded — verify assertions
                    emitter.emit(EV_NODE, node_id="agentic", role="verifier", name="verify", phase="assert")
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
            # Only engage when an actual action FAILED (to self-heal). If the
            # batch's actions all succeeded but an assertion didn't pass, we do
            # NOT keep wandering the UI — we stop and report the result. This
            # prevents the run from clicking around aimlessly after the goal's
            # main flow (e.g. submitting a form) already completed.
            if action_failed:
              while step_no < self.max_turns:
                # User pressed Stop in the UI — abort immediately.
                if is_agentic_stopped():
                    trace.error = trace.error or "stopped by user"
                    trace.stopped = True
                    emitter.emit(EV_ERROR, message="agentic run stopped by user")
                    break
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

                # Early stop: if the planner re-proposes a step it already
                # completed successfully without the page having advanced, the
                # goal flow is done — declare success instead of looping or
                # healing on a junk target.
                if action in _VALID_ACTIONS and action not in ("done", "fail", "navigate", "wait", "scroll", "screenshot") \
                        and _is_redundant_step(action, target, current_url, done_steps):
                    emitter.emit(EV_THINKING, node_id="agentic", text="goal flow already completed (redundant step) — stopping", phase="done")
                    performed = [s for s in trace.steps if s.action not in ("done", "fail", "navigate", "wait", "scroll", "screenshot")]
                    if performed and all(s.ok for s in performed):
                        trace.goal_reached = True
                        trace.success = True
                    break

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
                    emitter.emit(EV_NODE, node_id="agentic", role="verifier", name="verify", phase="assert")
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
                ok, detail, gave_up, f_tgt, f_knd, f_val = self._execute_with_heal(
                    action, target, kind, value, current_url, interactive, history, constraints, goal,
                )
                step = ActionTrace(
                    step=step_no,
                    action=action,
                    target=f_tgt,
                    kind=f_knd,
                    value=f_val,
                    ok=ok,
                    thought=thought,
                    detail=detail,
                    url=current_url,
                    interactive_elements=interactive[:40],
                    duration_ms=0.0,
                    timestamp=time.time(),
                )
                trace.steps.append(step)
                history.append(f"[{action}] {f_tgt} -> {'ok' if ok else 'FAIL: ' + detail}")
                if not ok:
                    logger.warning("agentic action failed: %s", detail)
                    trace.error = trace.error or f"{action} on '{f_tgt}' failed: {detail}"
                    action_failed = True
                    break
                else:
                    # Record successful steps so we can detect redundant re-plans.
                    post_url = bt.browser_get_url().get("url", current_url)
                    done_steps.append((action, f_tgt, post_url))

            if step_no >= self.max_turns and not trace.success:
                trace.error = trace.error or f"exceeded max_turns ({self.max_turns}) without reaching goal"
        except Exception as e:  # noqa: BLE001
            # Never let a planner/executor exception silently kill the NDJSON
            # stream — surface it as an error event and a trace error.
            logger.exception("agentic run crashed")
            trace.error = trace.error or f"agentic run crashed: {e}"
            emitter.emit(EV_ERROR, message=trace.error)
        finally:
            try:
                trace.final_url = bt.browser_get_url().get("url", "") if snap.get("ok") else ""
            except Exception:  # noqa: BLE001
                pass
            # NOTE: intentionally do NOT call bt.browser_stop() here. Keeping the
            # session alive after a run lets the LiveBrowser keep showing the
            # completed page instead of going blank, and lets repeated runs
            # reuse the same browser. browser_start() already recreates the
            # session (under lock) only when the headless mode actually differs.
            trace.total_duration_ms = (time.time() - start_ts) * 1000.0

        # Generate static Playwright test from successful trace. Reasoning is
        # streamed live (phase="codegen") via _streaming_infer while the stored
        # artifact is cleaned separately so the verbose model output never
        # lands in the final test file.
        generated_code = None
        successful_steps = [s for s in trace.steps if s.ok and s.action not in ("done", "fail")]
        # Fail-fast: never emit generated test code when an action failed.
        if successful_steps and not action_failed:
            emitter.emit(EV_NODE, node_id="agentic", role="generator", name="codegen", phase="codegen")
            from .trace_to_code import trace_to_code_refined
            try:
                generated_code = trace_to_code_refined(
                    trace,
                    llm_infer_fn=self._streaming_infer,
                )
                logger.info("generated %d-char refined test code from %d steps", len(generated_code), len(successful_steps))
            except Exception:  # noqa: BLE001
                logger.debug("failed to generate refined code, falling back to raw", exc_info=True)
                from .trace_to_code import trace_to_code
                try:
                    generated_code = trace_to_code(trace)
                except Exception:  # noqa: BLE001
                    pass

        # A user Stop request always wins, even if the run reached some end
        # state (success / fail-fast) before the loop observed the flag.
        if is_agentic_stopped() and not trace.stopped:
            trace.stopped = True
            trace.success = False
            trace.error = trace.error or "stopped by user"
            emitter.emit(EV_ERROR, message="agentic run stopped by user")

        emitter.emit(
            EV_DONE,
            success=trace.success,
            goal_reached=trace.goal_reached,
            stopped=trace.stopped,
            final_node="agentic",
            generated_code=generated_code,
            trace=trace.to_dict(),
            error=trace.error,
        )

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
            # Include the ARIA description as a third pipe segment so the
            # planner emits e.g. "link|JavaScript|Interactive and dynamic web
            # pages" with the space preserved (the snapshot's raw name has the
            # description glued on with no separator).
            desc = (e.get("description") or "").strip()
            s = f"- {e.get('role')}|{e.get('name')}"
            if desc:
                s += f"|{desc}"
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
        self.emitter.emit(EV_NODE, node_id="agentic", role="planner", name="batch-plan", phase="plan")

        # Retry with a firmer prompt if the model returns prose / unparseable
        # output — the planner is nondeterministic, so a second attempt usually
        # recovers the JSON block instead of silently ending the run.
        attempts = [
            prompt,
            prompt
            + "\n\nCRITICAL: Your previous attempt was not valid JSON. "
            "Output ONLY the raw JSON object now — starting with '{' and "
            "ending with '}'. No explanation, no markdown fences, no text "
            "before or after the object.",
        ]
        for attempt_idx, attempt_prompt in enumerate(attempts):
            parts: list[str] = []

            def _on_delta(kind: str, text: str) -> None:
                if text:
                    parts.append(text)
                    self.emitter.emit(EV_THINKING, node_id="agentic", text=text, phase="plan")

            try:
                llm_name, out = self.llm.stream_infer(
                    attempt_prompt, _on_delta, max_tokens=4096, temperature=0.0
                )
            except Exception:  # noqa: BLE001
                llm_name, out = None, ""
            if not out:
                logger.warning("batch planner: no LLM response (attempt %d)", attempt_idx + 1)
                continue
            logger.info(
                "batch planner raw output (%d chars, attempt %d): %s",
                len(out),
                attempt_idx + 1,
                out[:500],
            )
            batch = _extract_batch(out)
            if batch:
                logger.info("batch plan: %d actions (attempt %d)", len(batch), attempt_idx + 1)
                return batch
            logger.warning(
                "batch planner: no parseable actions (attempt %d, raw=%s)",
                attempt_idx + 1,
                out[:2000],
            )
        return None

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
            desc = (e.get("description") or "").strip()
            s = f"- {e.get('role')}|{e.get('name')}"
            if desc:
                s += f"|{desc}"
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
            self.emitter.emit(EV_NODE, node_id="agentic", role="planner", name="step-plan", phase="plan")

            def _on_delta(kind: str, text: str) -> None:
                if text:
                    self.emitter.emit(EV_THINKING, node_id="agentic", text=text, phase="plan")

            try:
                llm_name, out = self.llm.stream_infer(p, _on_delta, max_tokens=2048, temperature=0.0)
            except Exception:  # noqa: BLE001
                llm_name, out = None, ""
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
            elif action == "scroll":
                res = bt.browser_scroll(target, kind)
            elif action == "assert_visible":
                res = bt.browser_assert_visible(target, kind)
            elif action == "assert_text":
                res = bt.browser_assert_text(target, value, kind)
            elif action == "assert_url":
                res = bt.browser_assert_url(value)
            elif action == "screenshot":
                # Observation-only action: capture a frame for the live UI.
                # Never blocks goal progress; treated as a successful no-op.
                res = bt.browser_screenshot()
            else:
                return False, f"unsupported action {action}"
        except Exception as exc:  # noqa: BLE001
            self.emitter.emit(EV_TOOL_RESULT, name=f"browser_{action}", ok=False, error=str(exc))
            return False, str(exc)
        ok = bool(res.get("ok"))
        detail = res.get("error") or ("ok" if ok else "action returned ok=false")
        self.emitter.emit(EV_TOOL_RESULT, name=f"browser_{action}", ok=ok, result=str(res)[:200])
        return ok, detail

    def _is_locator_error(self, detail: str) -> bool:
        """Return True if ``detail`` looks like a locator/element-resolution
        failure that the self-heal loop can plausibly recover from by choosing a
        different element."""
        d = (detail or "").lower()
        return any(h in d for h in _LOCATOR_ERROR_HINTS)

    def _execute_with_heal(
        self,
        action: str,
        target: str,
        kind: str,
        value: str,
        url: str,
        interactive: list[dict[str, Any]],
        history: list[str],
        constraints: dict[str, Any],
        goal: str = "",
    ) -> tuple[bool, str, bool, str, str, str]:
        """Execute ``action`` and, on a locator error, autonomously retry by
        re-observing the page and asking the planner for a corrected locator.

        Returns ``(ok, detail, gave_up, final_target, final_kind, final_value)``.
        Up to ``MAX_LOCATOR_RETRIES`` attempts are made with no human
        intervention; the failure is fed back as live context each time.
        ``gave_up`` is True if we exhausted the retries. The final
        target/kind/value are the ones actually used (the corrected locator
        when healing succeeded), so the generated test captures the working
        selector.
        """
        ok, detail = self._execute_action(action, target, kind, value)
        if ok or not self._is_locator_error(detail):
            return ok, detail, False, target, kind, value

        attempt = 0
        last_target, last_kind, last_value = target, kind, value
        while attempt < MAX_LOCATOR_RETRIES:
            attempt += 1
            # User pressed Stop — abort the heal retries immediately.
            if is_agentic_stopped():
                history.append("[SELF-HEAL] stopped by user")
                return False, "stopped by user", True, last_target, last_kind, last_value
            # Re-observe the live page so the planner sees the current elements.
            # Scroll progressively (top->bottom across attempts) so elements that
            # were below the fold (e.g. a newsletter form) become visible and
            # resolvable — without human intervention.
            try:
                if attempt == 1:
                    bt.browser_scroll("top")
                else:
                    bt.browser_scroll("bottom" if attempt % 2 == 0 else "down")
            except Exception:  # noqa: BLE001
                pass
            snap = bt.browser_snapshot()
            new_interactive = snap.get("interactive_elements", []) if snap.get("ok") else interactive
            new_url = snap.get("url", url)

            # Query the LIVE DOM for elements relevant to the original intent so
            # self-heal reads the page instead of guessing. Ranked candidates are
            # tried in order across attempts — if the page genuinely has no
            # matching element this returns an empty list and we give up early.
            intent = self._heal_intent(action, target, value)
            dom = bt.browser_dom_candidates(intent, action_kind=action)
            dom_cands = dom.get("candidates", []) if dom.get("ok") else []

            # Build a concrete alternative locator candidate for THIS attempt so
            # that every attempt genuinely differs even if the planner stalls.
            candidate = self._heal_candidate(action, target, attempt, new_interactive, dom_cands)

            feedback = (
                f"[SELF-HEAL {attempt}/{MAX_LOCATOR_RETRIES}] The previous "
                f"'{action}' on '{last_target}' FAILED: {detail}. The locator did "
                f"not resolve on the current page. You MUST propose a DIFFERENT, "
                f"concrete locator for the same intent — do NOT say 'fail' or "
                f"'done', and do NOT repeat '{last_target}'. Prefer a role|name "
                f"from the VISIBLE INTERACTIVE ELEMENTS list below; if none match, "
                f"emit a css| selector you think is most likely (e.g. "
                f"'{candidate}'). This attempt, try: {candidate}."
            )
            history.append(feedback)
            self.emitter.emit(
                EV_THINKING,
                node_id="agentic",
                text=f"self-heal attempt {attempt}/{MAX_LOCATOR_RETRIES}: {detail} -> trying {candidate}",
                phase="heal",
            )

            plan = self._plan(
                goal=goal or f"{action} {target}",
                assertions=[],
                url=new_url,
                interactive=new_interactive,
                history=history,
                constraints=constraints,
            )
            new_action = plan.get("action", "fail")
            new_action = _ACTION_ALIASES.get(new_action, new_action)
            # Prefer the planner's concrete proposal; if it gave up / repeated
            # the bad locator, fall back to this attempt's generated candidate so
            # the attempt is never wasted on an identical string.
            proposed_target = plan.get("target", "") or plan.get("element", "")
            if (
                new_action in _VALID_ACTIONS
                and new_action not in ("done", "fail")
                and proposed_target
                and proposed_target != last_target
            ):
                last_target = proposed_target
                last_kind = plan.get("kind", "auto")
                # Keep the original value (e.g. the email text) if the planner
                # does not supply one.
                last_value = plan.get("value", "") or value
            else:
                if new_action in ("done", "fail") or not proposed_target:
                    history.append(
                        f"[SELF-HEAL {attempt}/{MAX_LOCATOR_RETRIES}] planner gave no "
                        f"new locator; using generated candidate '{candidate}'."
                    )
                last_target, last_kind, last_value = candidate, "css", value

            # Execute the original action (type/click/select/...) with whatever
            # locator we resolved — the heal is about fixing the *locator*, not
            # the action. Fall back to the original action if the planner
            # returned done/fail.
            exec_action = (
                new_action
                if new_action in _VALID_ACTIONS and new_action not in ("done", "fail")
                else action
            )
            ok, detail = self._execute_action(exec_action, last_target, last_kind, last_value)
            if ok:
                history.append(
                    f"[SELF-HEAL {attempt}/{MAX_LOCATOR_RETRIES}] recovered: "
                    f"'{new_action}' on '{last_target}' succeeded."
                )
                self.emitter.emit(
                    EV_THINKING,
                    node_id="agentic",
                    text=f"self-heal succeeded on attempt {attempt}",
                    phase="heal",
                )
                return True, detail, False, last_target, last_kind, last_value
            # Locator still failing — loop again with a fresh candidate.

        history.append(
            f"[SELF-HEAL] gave up after {MAX_LOCATOR_RETRIES} attempts: {detail}"
        )
        return False, detail, True, last_target, last_kind, last_value

    @staticmethod
    def _heal_intent(action: str, target: str, value: str) -> str:
        """Derive a keyword intent used to query the live DOM during heal.

        For a 'type email' action this yields 'email'; for a 'click subscribe'
        it yields 'subscribe submit'. We fold in the action, the original target
        text, and the value so the DOM scorer has the best signal to rank by.
        """
        parts = []
        a = (action or "").lower()
        if "type" in a or "fill" in a:
            parts.append("text")
        if "click" in a or "press" in a:
            parts.append("click")
        if value:
            parts.append(value)
        # Pull meaningful words out of the original target (role|name or css).
        o = (target or "").replace("|", " ").lower()
        parts.append(o)
        # Common field synonyms so a 'textbox|Email' target also scores email.
        if "email" in o or "mail" in o:
            parts.append("email")
        if "subscribe" in o or "newsletter" in o:
            parts.append("subscribe submit")
        if "search" in o or "query" in o:
            parts.append("search")
        if "password" in o or "pass" in o:
            parts.append("password")
        if "name" in o:
            parts.append("name")
        seen, out = set(), []
        for p in parts:
            if p and p not in seen:
                seen.add(p)
                out.append(p)
        return " ".join(out)

    @staticmethod
    def _heal_candidate(
        action: str,
        original: str,
        attempt: int,
        interactive: list[dict],
        dom_candidates: list[dict],
    ) -> str:
        """Generate a distinct locator candidate for a given heal attempt.

        Prefers **DOM-aware** candidates returned by the live page query (ranked
        by relevance to the intent), then falls back to cycling the visible
        interactive element list, then to intent-derived css| selectors. This
        means the heal loop reads what's *actually* on the page rather than
        spraying random elements.
        """
        # 1) Best: a real element the DOM scorer judged relevant to the intent.
        if dom_candidates:
            idx = (attempt - 1) % len(dom_candidates)
            c = dom_candidates[idx]
            loc = c.get("locator", "")
            if loc:
                return loc
        # 2) Fallback: a real visible element from the snapshot, cycling so
        #    successive attempts target different elements.
        if interactive:
            idx = (attempt - 1) % len(interactive)
            el = interactive[idx]
            role = el.get("role", "")
            name = el.get("name", "")
            if role and name:
                return f"{role}|{name}"
        # 3) Last resort: css| fallbacks derived from common intent keywords.
        o = (original or "").lower()
        fallbacks = [
            "css|input[type=email]",
            "css|input[name*=email i]",
            "css|input[placeholder*=email i]",
            "css|form input[type=text]",
            "css|input[type=text]",
            "css|input[type=search]",
            "css|textarea",
        ]
        if "email" in o:
            fallbacks = [
                "css|input[type=email]",
                "css|input[name*=email i]",
                "css|input[placeholder*=email i]",
                "css|input[type=text]",
            ] + fallbacks
        if "subscribe" in o or "search" in o:
            fallbacks = [
                "css|button[type=submit]",
                "css|input[type=submit]",
                "css|button",
                "css|a[href]",
            ] + fallbacks
        return fallbacks[(attempt - 1) % len(fallbacks)]

    def _verify_assertions(self, assertions: list[dict[str, Any]]) -> list[AssertionResult]:
        """Verify assertions.

        Free-text assertions (a ``text`` assertion, or a ``visibility``
        assertion whose target is plain wording rather than a locator) are
        checked mechanically and, crucially, *polled* for a few seconds so a
        success/confirmation message that renders a beat after a submit is
        caught. The LLM judge is only used for genuinely ambiguous,
        locator-based assertions. This avoids the common failure where the
        assertion runs a moment before the page updates and wrongly reports
        the expected text as missing.
        """
        import time as _time

        results: list[AssertionResult] = []
        deadline = _time.time() + 8.0
        for i, a in enumerate(assertions):
            atype = a.get("type", "visibility")
            desc = a.get("description", atype)
            mech = self._assert_mechanical(a, atype)
            # For text-bearing assertions, poll the page until either the text
            # appears or the deadline passes — then stop overriding with the LLM.
            if mech is not None and not mech.passed:
                still_polling = True
                while still_polling and _time.time() < deadline:
                    _time.sleep(0.75)
                    mech = self._assert_mechanical(a, atype)
                    if mech.passed:
                        break
                    # Re-evaluate whether it's worth continuing to wait: only
                    # keep polling for assertions that look text-based.
                    still_polling = self._is_text_assertion(a, atype)
            if mech is not None and mech.passed:
                results.append(mech)
                continue
            # Mechanical check couldn't confirm (or assertion is locator-based);
            # consult the LLM judge for an authoritative verdict on ambiguous
            # assertions. Free-text failures after polling are left as the
            # mechanical result (don't let the LLM overrule a clear text check).
            snap = bt.browser_snapshot()
            url = bt.browser_get_url().get("url", "")
            llm_results = self._judge_assertions_llm([a], snap, url)
            if (
                llm_results is not None
                and llm_results
                and llm_results[0] is not None
                and not self._is_text_assertion(a, atype)
            ):
                results.append(llm_results[0])
                continue
            results.append(mech if mech is not None else AssertionResult(
                type=atype, description=desc, passed=False, detail="assertion not met"))
        return results

    def _is_text_assertion(self, a: dict[str, Any], atype: str) -> bool:
        """True for assertions whose expected value is free text on the page
        (not a locatable element). We poll/wait for these."""
        if atype == "text":
            return bool(a.get("expected"))
        if atype == "visibility":
            tgt = a.get("target", "")
            return bool(tgt) and "|" not in tgt and not tgt.startswith(("#", ".", "[", "/"))
        return False

    def _assert_mechanical(self, a: dict[str, Any], atype: str) -> Optional[AssertionResult]:
        """Run the mechanical check for a single assertion. Returns None when
        the assertion type is not mechanically checkable (caller consults LLM)."""
        desc = a.get("description", atype)
        try:
            if atype == "visibility":
                tgt = a.get("target", "")
                res = bt.browser_assert_visible(tgt, a.get("kind", "auto"))
                passed = bool(res.get("ok"))
                if not passed and tgt and "|" not in tgt and not tgt.startswith(("#", ".", "[", "/")):
                    txt_res = bt.browser_assert_text(tgt, "", a.get("kind", "auto"))
                    if txt_res.get("ok"):
                        return AssertionResult(type=atype, description=desc, passed=True, detail="")
                    detail = res.get("error") or f"not visible: {tgt}"
                else:
                    detail = "" if passed else (res.get("error") or f"not visible: {tgt}")
                return AssertionResult(type=atype, description=desc, passed=passed, detail=detail)
            elif atype == "text":
                res = bt.browser_assert_text(a.get("expected", ""), a.get("target", ""), a.get("kind", "auto"))
                passed = bool(res.get("ok"))
                return AssertionResult(
                    type=atype, description=desc, passed=passed,
                    detail="" if passed else f"text not found: {a.get('expected')}")
            elif atype == "url":
                res = bt.browser_assert_url(a.get("pattern", ""))
                passed = bool(res.get("ok"))
                return AssertionResult(
                    type=atype, description=desc, passed=passed,
                    detail="" if passed else f"url mismatch: {res.get('url')}")
        except Exception as exc:  # noqa: BLE001
            return AssertionResult(type=atype, description=desc, passed=False, detail=str(exc))
        return None

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
            def _on_delta(kind: str, text: str) -> None:
                if text:
                    self.emitter.emit(EV_THINKING, node_id="agentic", text=text, phase="assert")

            _name, out = self.llm.stream_infer(prompt, _on_delta, max_tokens=1024, temperature=0.0)
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
