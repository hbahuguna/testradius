# sdet_agent/reasoning/llm_reasoner.py
from __future__ import annotations
import logging
import re
from typing import Callable, Optional, Tuple

from ..core.state import AgentState, NodeResult
from ..core.events import EV_THINKING, EV_CONTENT, EventEmitter
from .llm_factory import LLMFactory, LLMClientConfig # Import LLMFactory and LLMClientConfig
from .qwen_client import QwenClient # Keep for config
from .hy3_client import Hy3Client # Keep for config
from .templates import NODE_SYSTEM_PROMPTS
from .rule_reasoner import (
    classify_intent,
    classify_feature,
    generate_code_template,
)

logger = logging.getLogger("sdet_agent.llm_reasoner")

def extract_code(response: str) -> str:
    """Pull the most substantial fenced code block out of a model reply.

    Accepts any language tag (typescript, ts, tsx, js, playwright, ...) and is
    case-insensitive, since reasoning models vary in how they fence the code.
    Also tolerates an unclosed final fence (the model sometimes omits the
    closing ```), capturing to end-of-response. Falls back to the raw
    response when it already looks like code.
    """
    blocks = re.findall(r"```(?:[a-zA-Z]+)?\s*\n(.*?)```", response, re.DOTALL)
    if not blocks:
        # Unclosed opening fence: capture everything after it to EOF.
        m = re.search(r"```(?:[a-zA-Z]+)?\s*\n(.*)$", response, re.DOTALL)
        if m:
            blocks = [m.group(1)]
    if blocks:
        return max(blocks, key=len).strip()
    # Fallback: if the whole response looks like code, return it
    if response.strip().startswith("import") or "test(" in response:
        return response.strip()
    return ""


class LLMReasoner: # Renamed from QwenReasoner
    def __init__(self, llm_factory: Optional[LLMFactory] = None, emitter: Optional[EventEmitter] = None):
        # Default LLM factory setup
        if llm_factory is None:
            # hy3-free (OpenCode Zen) is the project's default model; Qwen is a
            # secondary option. The factory falls through to the next healthy
            # client if the primary is unreachable or errors.
            client_configs = [
                LLMClientConfig(name="hy3-free", client_class=Hy3Client),
                LLMClientConfig(name="qwen", client_class=QwenClient),
            ]
            self.llm_factory = LLMFactory(client_configs)
        else:
            self.llm_factory = llm_factory
        self.emitter = emitter

    def _build_prompt(self, node_id: str, state: AgentState) -> str:
        system = NODE_SYSTEM_PROMPTS.get(node_id, "You are an expert Senior SDET.")
        journal = state.scratchpad.load_journal()
        history = state.conversation_history()
        scenario = state.scenario
        url = state.url
        feature = state.get("feature_type", "form")
        intent = state.get("intent", "positive")

        if node_id == "N14":
            jira_rule = (
                "PRIORITY RULES (must follow):\n"
                "- If the scenario contains a 'JIRA CONTEXT' section, it is the AUTHORITATIVE "
                "source of test requirements and expected behavior. Drive the test from it first.\n"
                "- If the scenario also contains a 'RECORDED ACTIONS' section, include those "
                "actions ONLY where they do NOT conflict with the Jira ticket. On any conflicting "
                "step (same field/action with different value or intent), use the JIRA version.\n"
                "- The final test is the UNION of both: every Jira-required step is covered, plus "
                "any non-conflicting recorded action. If only one section is present, use it alone.\n"
            )
            return (
                f"{system}\n\n"
                "Generate ONE Playwright test in TypeScript.\n"
                "RULES (the test is rejected by guardrails unless ALL hold):\n"
                "- Use ONLY accessible locators, in priority order: getByRole > getByLabel "
                "> getByPlaceholder > getByText. NEVER use page.locator('#id'), CSS selectors, "
                "or page.click('text=...').\n"
                "- After EVERY action (fill/click/select/check), add an expect() assertion "
                "(toBeVisible / toHaveValue / toBeEnabled / toHaveURL).\n"
                "- Include test.beforeEach that calls page.goto('<URL>').\n"
                "- NO fixed timeouts (no waitForTimeout, no page.waitForSelector).\n"
                "- Output ONLY a single ```typescript fenced code block, with no commentary "
                "outside it.\n\n"
                f"{jira_rule}"
                f"Target URL: {url}\n"
                f"Feature type: {feature}\nTest intent: {intent}\n\n"
                f"Scenario (test inputs to automate):\n{scenario}\n\n"
                f"<journal>\n{journal}\n</journal>\n"
            )
        return (
            f"{system}\n\n"
            f"Scenario: {scenario}\nTarget URL: {url}\n\n"
            f"<journal>\n{journal}\n</journal>\n\n"
            f"<history>\n{history}\n</history>\n\n"
            "Respond concisely with the structured analysis for this step."
        )

    def reason(self, node_id: str, state: AgentState) -> Tuple[Optional[str], str]:
        """Performs inference using the first available LLM, returns (llm_name, response)."""
        prompt = self._build_prompt(node_id, state)
        llm_name, out = self.llm_factory.infer(prompt, max_tokens=8192 if node_id == "N14" else 640)
        if not llm_name:
            logger.warning("No healthy LLM available for node %s, falling back to rules.", node_id)
            return None, ""
        return llm_name, out

    def stream_reason(
        self, node_id: str, state: AgentState, on_delta=None
    ) -> Tuple[Optional[str], str]:
        """Streams inference for a node, routing deltas to ``on_delta`` or this
        reasoner's ``emitter``. Returns (llm_name, full_text).

        Deltas are buffered and flushed in larger chunks (on newline or when a
        chunk reaches ~120 chars) so the UI receives readable, wrapping lines
        instead of one WebSocket message per model token.
        """
        prompt = self._build_prompt(node_id, state)
        emitter = self.emitter
        buf = {"reasoning": "", "content": ""}

        def _flush(kind: str) -> None:
            text = buf[kind]
            if not text:
                return
            buf[kind] = ""
            if emitter is None:
                return
            if kind == "reasoning":
                emitter.emit(EV_THINKING, node_id=node_id, text=text)
            else:
                emitter.emit(EV_CONTENT, node_id=node_id, text=text)

        def _default_on_delta(kind: str, text: str) -> None:
            buf[kind] += text
            if len(buf[kind]) >= 120 or "\n" in text:
                _flush(kind)

        callback = on_delta or _default_on_delta
        llm_name, out = self.llm_factory.stream_infer(
            prompt, callback, max_tokens=8192 if node_id == "N14" else 640
        )
        # Flush any remaining buffered text.
        _flush("reasoning")
        _flush("content")
        if not llm_name:
            logger.warning("No healthy LLM available for node %s, falling back to rules.", node_id)
            return None, ""
        return llm_name, out


def build_llm_handlers(reasoner: LLMReasoner) -> dict[str, Callable[[AgentState], NodeResult]]: # Renamed from build_qwen_handlers
    """Return node_id -> handler mappings that use LLMReasoner with rule fallback."""

    def make(node_id: str, fallback_fn: Callable[[AgentState], str], store_key: Optional[str] = None):
        def handler(state: AgentState) -> NodeResult:
            if reasoner.emitter is not None:
                llm_name, raw = reasoner.stream_reason(node_id, state)
            else:
                llm_name, raw = reasoner.reason(node_id, state)
            used_fallback = False
            if not raw:
                raw = fallback_fn(state)
                used_fallback = True
            if store_key:
                state.set(store_key, raw)
            return NodeResult(
                node_id=node_id,
                role="agent",
                content=raw,
                metadata={"source": "rule-fallback" if used_fallback else llm_name},
            )
        return handler

    def make_identify_elements(state: AgentState) -> NodeResult:
        # Real tool execution. ToolRegistry.call() emits tool_call/tool_result
        # events itself, so the DOM parse shows up in the OpenCode-style stream.
        url = state.url or ""
        desc = "Identified interactable elements from the scenario."
        if url:
            try:
                from ..tools import build_registry

                elements = build_registry().call("dom_analyze", {"url": url})
                if isinstance(elements, list) and elements and "error" not in elements[0]:
                    picks = [e.get("suggested_locator") for e in elements[:12] if e.get("suggested_locator")]
                    desc = (
                        f"Analyzed {url} and found {len(elements)} interactive elements. "
                        f"Locator hints: " + "; ".join(picks)
                    )
                    state.set("dom_elements", elements)
            except Exception as exc:  # noqa: BLE001
                logger.warning("dom_analyze failed for %s: %s", url, exc)
        return NodeResult(node_id="N9", role="agent", content=desc)

    def make_code(state: AgentState) -> NodeResult:
        if reasoner.emitter is not None:
            llm_name, raw = reasoner.stream_reason("N14", state)
        else:
            llm_name, raw = reasoner.reason("N14", state)
        code = extract_code(raw) if raw else ""
        if not code:
            code = generate_code_template(state)
            source = "rule-fallback"
        else:
            source = llm_name # Store LLM name
        if reasoner.emitter is not None and code:
            reasoner.emitter.emit(EV_CONTENT, node_id="N14", text=code)
        state.set("generated_code", code)
        return NodeResult(
            node_id="N14",
            role="agent",
            content=f"Generated Playwright test:\n\n```typescript\n{code}\n```",
            metadata={"source": source},
        )
    return {
        "N2": make("N2", lambda s: classify_feature(s.scenario).reasoning),
        "N5": make("N5", lambda s: classify_intent(s.scenario).reasoning, store_key="intent_reasoning"),
        "N9": make_identify_elements,
        "N11": make("N11", lambda s: "Action sequence planned from scenario steps."),
        "N14": make_code,
    }
