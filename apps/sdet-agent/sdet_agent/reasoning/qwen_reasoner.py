"""Qwen-backed reasoning for generative graph nodes.

Phase 2 upgrades the five generative nodes to call the fine-tuned Qwen SLM
instead of the rule-based placeholders:

  N2  ParseRequirement   -> concise requirement analysis
  N5  DetermineIntent    -> intent classification (positive/negative/...)
  N9  IdentifyElements    -> element list with Playwright roles
  N11 PlanActions        -> action sequence
  N14 GenerateCode        -> final Playwright TypeScript

Routing hubs (N3, N6, N8, N15) stay rule-based (textbook Ch.4: deterministic
guardrails). The reasoner degrades gracefully to rule-based output when the
model is unreachable.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Optional

from ..core.state import AgentState, NodeResult
from .qwen_client import QwenClient
from .templates import NODE_SYSTEM_PROMPTS
from .rule_reasoner import (
    classify_intent,
    classify_feature,
    generate_code_template,
)

logger = logging.getLogger("sdet_agent.qwen")


def extract_code(response: str) -> str:
    """Pull the first fenced code block (any language) out of a model reply."""
    m = re.search(r"```(?:typescript|ts|js|javascript|playwright)?\s*\n(.*?)```", response, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Fallback: if the whole response looks like code, return it
    if response.strip().startswith("import") or "test(" in response:
        return response.strip()
    return ""


class QwenReasoner:
    def __init__(self, client: Optional[QwenClient] = None):
        self.client = client or QwenClient()

    def _build_prompt(self, node_id: str, state: AgentState) -> str:
        system = NODE_SYSTEM_PROMPTS.get(node_id, "You are an expert Senior SDET.")
        journal = state.scratchpad.load_journal()
        history = state.conversation_history()
        scenario = state.scenario
        url = state.url
        feature = state.get("feature_type", "form")
        intent = state.get("intent", "positive")

        if node_id == "N14":
            return (
                f"{system}\n\n"
                f"Target URL: {url}\n"
                f"Feature type: {feature}\nTest intent: {intent}\n"
                f"Scenario: {scenario}\n\n"
                f"<journal>\n{journal}\n</journal>\n\n"
                "Output ONLY valid Playwright TypeScript in a single ```typescript code block. "
                "Follow the Page Object Model where page objects exist; otherwise use raw "
                "accessible locators (getByRole/getByLabel/getByText). Include beforeEach, "
                "auto-waiting assertions, and no fixed timeouts."
            )
        return (
            f"{system}\n\n"
            f"Scenario: {scenario}\nTarget URL: {url}\n\n"
            f"<journal>\n{journal}\n</journal>\n\n"
            f"<history>\n{history}\n</history>\n\n"
            "Respond concisely with the structured analysis for this step."
        )

    def reason(self, node_id: str, state: AgentState) -> str:
        prompt = self._build_prompt(node_id, state)
        try:
            out = self.client.infer(prompt, max_tokens=1024 if node_id == "N14" else 512)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Qwen call failed at %s: %s", node_id, exc)
            out = ""
        if out.startswith("[Qwen error"):
            logger.warning("Qwen unavailable at %s, falling back to rules", node_id)
            return ""
        return out


def build_qwen_handlers(reasoner: QwenReasoner) -> dict[str, Callable[[AgentState], NodeResult]]:
    """Return node_id -> handler mappings that use Qwen with rule fallback."""

    def make(node_id: str, fallback_fn: Callable[[AgentState], str], store_key: Optional[str] = None):
        def handler(state: AgentState) -> NodeResult:
            raw = reasoner.reason(node_id, state)
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
                metadata={"source": "rule-fallback" if used_fallback else "qwen"},
            )
        return handler

    def make_code(state: AgentState) -> NodeResult:
        raw = reasoner.reason("N14", state)
        code = extract_code(raw) if raw else ""
        if not code:
            code = generate_code_template(state)
            source = "rule-fallback"
        else:
            source = "qwen"
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
        "N9": make("N9", lambda s: "Identified interactable elements from scenario."),
        "N11": make("N11", lambda s: "Action sequence planned from scenario steps."),
        "N14": make_code,
    }
