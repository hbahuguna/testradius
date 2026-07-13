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
    "> getByPlaceholder > getByText). Output ONLY a single ```typescript fenced "
    "code block with the full corrected test."
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


def _extract_locators(code: str) -> list[tuple[str, str]]:
    """Return [(method, name)] for every getBy* locator in the code."""
    out: list[tuple[str, str]] = []
    for m in _LOCATOR_RE.finditer(code):
        method = m.group(1)
        name = m.group(2) or m.group(3) or m.group(4) or ""
        out.append((method, name))
    return out


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

            prompt = (
                f"{_HEAL_SYSTEM}\n\n"
                f"ERROR OUTPUT:\n{error_output[:1500]}\n\n"
                f"{line_hint}{failing_snippet}\n\n"
                f"CURRENT PAGE URL: {snap.get('url', url)}\n"
                f"CURRENT INTERACTIVE ELEMENTS:\n{elem_lines}\n\n"
                f"ORIGINAL TEST CODE:\n```typescript\n{original}\n```\n"
            )
            llm_name, out = self.llm.infer(prompt, max_tokens=2048, temperature=0.2)
            if not out:
                return HealResult(False, original, "", [], {}, "no LLM response for healing")
            healed = extract_code(out)
            if not healed:
                return HealResult(False, original, "", [], {}, "LLM did not return code block")

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
