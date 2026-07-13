"""Self-healing for deterministic Playwright tests (agentic layer).

When a CI test fails due to a UI change that is NOT a functional regression
(the exact case Slack's agentic testing targets), the SelfHealer uses a live
browser session to re-explore the page at the point of failure, then asks the
LLM to rewrite the broken locator/assertion. The corrected code is verified by
checking that its locators actually resolve on the current page before being
returned -- reducing flaky failures caused by superficial DOM changes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
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
from ..tools import browser_tools as bt
from ..reasoning.llm_factory import LLMFactory, LLMClientConfig
from ..reasoning.hy3_client import Hy3Client
from ..reasoning.qwen_client import QwenClient
from ..reasoning.llm_reasoner import extract_code

logger = logging.getLogger("sdet_agent.self_healer")

# Capture locators of the form getByRole('button', { name: /X/i }) etc.
_LOCATOR_RE = re.compile(
    r"getBy(Role|Label|Text|Placeholder|TestId|AltText|Title)\(\s*"
    r"(?:/([^/]+)/|'([^']*)'|\"([^\"]*)\")"
    r"(?:[^)]*)?\)",
    re.IGNORECASE,
)

_HEAL_SYSTEM = (
    "You are an expert SDET maintaining a Playwright test that just failed. "
    "A UI change (not a functional regression) likely broke a selector or "
    "assertion. You are given the failing test code, the error message, the "
    "line that failed, and the CURRENT interactive elements on the live page. "
    "Rewrite the test so it works against the current UI, preserving the same "
    "intent and all accessible-locator best practices (getByRole > getByLabel "
    "> getByPlaceholder > getByText). "
    "CRITICAL: You MUST replace the failing locator with one of the suggested "
    "matching elements listed below. Never keep the old locator string -- doing "
    "so just reproduces the same failure. Output ONLY a single ```typescript "
    "fenced code block with the full corrected test (no explanation)."
)


@dataclass
class HealResult:
    success: bool
    original_code: str
    healed_code: str
    changed_locators: list[str]
    verification: dict[str, Any]
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "original_code": self.original_code,
            "healed_code": self.healed_code,
            "changed_locators": self.changed_locators,
            "verification": self.verification,
            "error": self.error,
        }


def _default_factory() -> LLMFactory:
    return LLMFactory(
        [
            LLMClientConfig(name="hy3-free", client_class=Hy3Client),
            LLMClientConfig(name="qwen", client_class=QwenClient),
        ]
    )


_LOC_CALL_START = re.compile(
    r"getBy(Role|Label|Text|Placeholder|TestId|AltText|Title)\(",
    re.IGNORECASE,
)


def _split_locator_calls(code: str) -> list[str]:
    """Return each top-level getBy* call (balanced parens) as a string."""
    calls: list[str] = []
    for m in _LOC_CALL_START.finditer(code):
        i = m.end() - 1  # index of the opening '('
        depth = 0
        j = i
        while j < len(code):
            if code[j] == "(":
                depth += 1
            elif code[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        calls.append(code[m.start(): j + 1])
    return calls


def _parse_locator_call(call: str) -> tuple[str, str]:
    """Parse a single getBy* call into (method, name).

    Prefers the explicit ``name:`` argument (e.g. ``getByRole('combobox',
    { name: /X/i })`` -> ('Role', 'X')) and falls back to the first
    string/regex argument.
    """
    m = re.match(
        r"getBy(Role|Label|Text|Placeholder|TestId|AltText|Title)\(",
        call,
        re.IGNORECASE,
    )
    if not m:
        return ("", "")
    method = m.group(1)
    body = call[m.end():]
    nm = None
    nm_m = re.search(
        r"name:\s*(?:/([^/]+)/|'([^']*)'|\"([^\"]*)\")",
        body,
    )
    if nm_m:
        nm = nm_m.group(1) or nm_m.group(2) or nm_m.group(3)
    if not nm:
        am = re.search(r"(?:/([^/]+)/|'([^']*)'|\"([^\"]*)\")", body)
        if am:
            nm = am.group(1) or am.group(2) or am.group(3)
    return (method, (nm or "").strip())


def _extract_locators(code: str) -> list[tuple[str, str]]:
    """Return [(method, name)] for every getBy* locator in the code."""
    return [_parse_locator_call(c) for c in _split_locator_calls(code)]


def _parse_failing_locator(error_output: str, original: str, failing_line: int | None) -> tuple[str, str] | None:
    """Best-effort extraction of the failing locator (method, name hint)."""
    candidates = [error_output]
    if failing_line and 1 <= failing_line <= len(original.splitlines()):
        candidates.append(original.splitlines()[failing_line - 1])
    candidates.append(original)
    for src in candidates:
        calls = _split_locator_calls(src)
        if calls:
            method, name = _parse_locator_call(calls[0])
            if method:
                return (method, name)
    return None


def _build_match_hints(
    failing: tuple[str, str] | None, interactive: list[dict]
) -> str:
    """Surface the current page elements that match the failed field, so the
    model replaces the broken locator with a real one instead of echoing it."""
    if not failing or not interactive:
        return ""
    method, name = failing
    role = method.lower()
    cands: list[str] = []
    for e in interactive:
        erole = (e.get("role") or "").lower()
        ename = e.get("name") or ""
        if role == "role":
            if erole in ("combobox", "select", "listbox", "button", "link",
                         "textbox", "checkbox", "menuitem", "option"):
                cands.append(f"{erole}|{ename}")
        else:
            if name and name.lower() in ename.lower():
                cands.append(f"{erole}|{ename}")
    if not cands:
        # Fallback: any select-like control on the page is a plausible target.
        cands = [
            f"{e.get('role')}|{e.get('name')}"
            for e in interactive
            if (e.get("role") or "").lower() in ("combobox", "select", "listbox")
        ]
    if not cands:
        return ""
    uniq = list(dict.fromkeys(cands))[:12]
    return (
        "ELEMENTS THAT MATCH THE FAILED FIELD (use ONE of these as the "
        "replacement locator):\n" + "\n".join(f"- {c}" for c in uniq)
    )


_LOC_CALL_RE = re.compile(
    r"getBy(?:Role|Label|Text|Placeholder|TestId|AltText|Title)\([^)]*\)"
)


def _clean_name(name: str) -> str:
    """Normalise a locator name hint (regex literal or quoted string)."""
    n = name.strip()
    if len(n) >= 2 and n.startswith("/") and n.endswith("/"):
        n = n[1:-1]
    elif len(n) >= 3 and n.startswith("/") and n[-1] in "imsu" and n[-2] == "/":
        n = n[1:-2]
    return n.strip("'\"").strip()


def _programmatic_fix(
    original: str, failing: tuple[str, str] | None, interactive: list[dict]
) -> str | None:
    """Deterministically rewrite the single failing locator using the live page.

    This is far more reliable than asking a reasoning model to rewrite the whole
    test. We match the failed field to a real current element and substitute the
    locator in place, leaving the rest of the test untouched.

    Returns the corrected code, or ``None`` when the match is ambiguous / absent
    (caller should fall back to the LLM).
    """
    if not failing or not interactive:
        return None
    method, name = failing
    name_clean = _clean_name(name).lower()

    # Identify candidate replacement elements.
    cands: list[dict] = []
    is_select_field = (
        method.lower() == "role"
        or "role" in name_clean
        or "select" in name_clean
    )
    for e in interactive:
        erole = (e.get("role") or "").lower()
        ename = (e.get("name") or "").strip()
        if not ename:
            continue
        if is_select_field and erole in ("combobox", "select", "listbox"):
            cands.append(e)
        elif name_clean and (name_clean in ename.lower() or ename.lower() in name_clean):
            cands.append(e)

    if not cands:
        return None
    # For combobox/select/listbox fields the failing locator usually used the
    # option/placeholder text, NOT the accessible (label) name. The correct
    # target is the candidate whose accessible name is the label -- which is the
    # shortest, label-like name. Prefer that over a hint substring match, which
    # would otherwise re-pick the option-text duplicate.
    if is_select_field:
        cands.sort(key=lambda e: len((e.get("name") or "").strip()))
        best = cands[0]
    else:
        best = None
        for e in cands:
            if name_clean and name_clean in (e.get("name") or "").lower():
                best = e
                break
        if best is None:
            best = cands[0]
    erole = (best.get("role") or "").lower()
    ename = best.get("name")

    if erole in ("combobox", "select", "listbox", "textbox", "checkbox", "radio", "searchbox"):
        repl = f"getByLabel(/{ename}/i)"
    else:
        repl = f"getByRole('{erole}', {{ name: /{ename}/i }})"

    # Replace only the locator call that contains the failing name hint.
    def _sub(m: re.Match) -> str:
        if name_clean and name_clean in m.group(0).lower():
            return repl
        return m.group(0)

    new_code = _LOC_CALL_RE.sub(_sub, original)
    if new_code == original:
        # Name hint didn't match a call; replace the first call of the same method.
        if method:
            pat = re.compile(
                r"getBy" + re.escape(method)
                + r"\([^)]*\)"
            )
            new_code = pat.sub(repl, original, count=1)
    return new_code if new_code != original else None


class SelfHealer:
    """Re-explore a failing UI and propose a corrected Playwright test."""

    def __init__(
        self,
        llm_factory: Optional[LLMFactory] = None,
        emitter=None,
        backend: str = "mcp",
        headless: bool = True,
    ):
        self.llm = llm_factory or _default_factory()
        self.emitter = emitter or _NoopEmitter()
        self.backend = backend
        self.headless = headless

    def heal(
        self,
        test_path: str,
        error_output: str,
        url: str,
        failing_line: Optional[int] = None,
    ) -> HealResult:
        emitter = self.emitter
        emitter.emit(EV_NODE, node_id="heal", role="agent", name="self-heal")
        try:
            with open(test_path, "r", encoding="utf-8") as fh:
                original = fh.read()
        except Exception as exc:  # noqa: BLE001
            return HealResult(False, "", "", [], {}, f"cannot read test: {exc}")

        emitter.emit(EV_THINKING, node_id="heal", text="Launching browser to re-explore failing page")
        start = bt.browser_start(headless=self.headless, backend=self.backend)
        if start.get("status") == "error":
            err = start.get("error", "browser start failed")
            emitter.emit(EV_ERROR, message=err)
            return HealResult(False, original, "", [], {}, err)
        try:
            bt.browser_navigate(url)
            snap = bt.browser_snapshot()
            interactive = snap.get("interactive_elements", []) if snap.get("ok") else []
            elem_lines = "\n".join(f"- {e.get('role')}|{e.get('name')}" for e in interactive[:80]) or "(none)"

            line_hint = f"Failing line (~{failing_line}): " if failing_line else "Failing line: "
            failing_snippet = ""
            if failing_line and 1 <= failing_line <= len(original.splitlines()):
                failing_snippet = original.splitlines()[failing_line - 1]

            failing_loc = _parse_failing_locator(error_output, original, failing_line)
            match_hints = _build_match_hints(failing_loc, interactive)

            # Fast, deterministic path: rewrite the single broken locator from
            # the live page. This avoids the flaky reasoning-model rewrite and is
            # what makes the self-heal reliably converge on form-locator fixes.
            prog = _programmatic_fix(original, failing_loc, interactive)
            if prog:
                changed = self._diff_locators(original, prog)
                verification = self._verify_locators(prog)
                ok = bool(verification.get("all_resolved"))
                emitter.emit(
                    EV_DONE,
                    success=ok,
                    final_node="heal",
                    error=None if ok else "locators unresolved",
                )
                logger.info(
                    "programmatic heal: changed=%s resolved=%s",
                    changed,
                    verification.get("all_resolved"),
                )
                return HealResult(
                    success=ok,
                    original_code=original,
                    healed_code=prog,
                    changed_locators=changed,
                    verification=verification,
                )

            prompt = (
                f"{_HEAL_SYSTEM}\n\n"
                f"ERROR OUTPUT:\n{error_output[:1500]}\n\n"
                f"{line_hint}{failing_snippet}\n\n"
                f"CURRENT PAGE URL: {snap.get('url', url)}\n"
                f"CURRENT INTERACTIVE ELEMENTS:\n{elem_lines}\n\n"
                f"{match_hints}\n\n"
                f"ORIGINAL TEST CODE:\n```typescript\n{original}\n```\n"
            )
            # hy3-free is a reasoning model and occasionally returns prose with no
            # fenced code block. Retry a few times with varied temperature before
            # giving up -- a transient prose response should not abort the heal.
            healed = ""
            last_raw = ""
            last_err = "LLM did not return code block"
            for attempt_temp in (0.2, 0.4, 0.6):
                _, out = self.llm.infer(prompt, max_tokens=4096, temperature=attempt_temp)
                last_raw = out or ""
                if not out:
                    last_err = "no LLM response for healing"
                    continue
                # Surface the real upstream failure (e.g. a missing API key or a
                # 4xx/5xx from OpenCode Zen) instead of the generic "no code block"
                # message, so the self-heal loop and the server logs show the cause.
                if out.lstrip().startswith("[Hy3 error") or "Hy3 error" in out:
                    last_err = out.strip()[:400]
                    logger.error("heal LLM returned an error: %s", last_err)
                    break
                healed = extract_code(out)
                if healed:
                    break
                logger.warning(
                    "heal attempt (temp=%s) returned no code block; retrying",
                    attempt_temp,
                )
            if not healed:
                logger.error(
                    "heal LLM returned no code block after retries (first 400 chars): %s",
                    last_raw.strip()[:400],
                )
                return HealResult(False, original, "", [], {}, last_err)

            changed = self._diff_locators(original, healed)
            verification = self._verify_locators(healed)
            ok = bool(verification.get("all_resolved"))
            emitter.emit(EV_DONE, success=ok, final_node="heal", error=None if ok else "locators unresolved")
            return HealResult(
                success=ok,
                original_code=original,
                healed_code=healed,
                changed_locators=changed,
                verification=verification,
            )
        finally:
            bt.browser_stop()

    # ------------------------------------------------------------------ #
    def _diff_locators(self, before: str, after: str) -> list[str]:
        b = {(m, n) for m, n in _extract_locators(before)}
        a = {(m, n) for m, n in _extract_locators(after)}
        return [f"{m}:{n}" for m, n in (a - b)]

    def _verify_locators(self, code: str) -> dict[str, Any]:
        """Check that every locator in the healed code resolves on the current page."""
        locators = _extract_locators(code)
        results: list[dict[str, Any]] = []
        for method, name in locators:
            kind = method.lower()
            target = name
            try:
                if kind == "role":
                    # name may be like "button|Submit" or just the name
                    if "|" in name:
                        role, _, nm = name.partition("|")
                        res = bt.browser_assert_visible(f"{role}|{nm}", "role")
                    else:
                        res = bt.browser_assert_visible(name, "role")
                else:
                    res = bt.browser_assert_visible(target, kind)
                results.append({"locator": f"{method}({name})", "resolved": bool(res.get("ok"))})
            except Exception as exc:  # noqa: BLE001
                results.append({"locator": f"{method}({name})", "resolved": False, "error": str(exc)})
        all_resolved = all(r["resolved"] for r in results)
        return {"all_resolved": all_resolved, "locators": results}
