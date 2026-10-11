"""Result evaluation (step 7-10 of the flow).

Deterministic metrics are computed here (confidence, fallback, >30% safety cap);
the LLM only *phrases* the summary from a D11-safe context. If no LLM is
configured the deterministic summary is used directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from ..analyze import SAFETY_RATIO, TiaResult
from .context import build_context
from .prompts import evaluate_messages
from .intake import LLMCallable


@dataclass
class Evaluation:
    confidence: str
    fallback_used: bool
    safety_flag: bool
    impacted_ratio: Optional[float]
    summary: str
    next_actions: List[str] = field(default_factory=list)


def evaluate(
    result: TiaResult,
    *,
    total_tests_in_repo: Optional[int] = None,
    instrumented: Optional[bool] = None,
    evidence_fresh: Optional[bool] = None,
    llm: Optional[LLMCallable] = None,
    changed_file_paths: Optional[List[str]] = None,
) -> Evaluation:
    total = result.total_tests_in_repo or total_tests_in_repo
    ratio: Optional[float] = None
    safety = False
    if total and total > 0:
        ratio = result.total_affected_tests / total
        # A fallback already runs the full suite; don't nag about the >30% cap.
        safety = ratio > SAFETY_RATIO and not result.fallback_used

    context = build_context(
        repo=result.repo,
        pr_number=result.pr_number,
        changed_file_paths=changed_file_paths or [],
        symbols=[t.get("reason", "") for t in result.tests if t.get("reason")],
        tests_selected=result.tests_selected,
        total_affected_tests=result.total_affected_tests,
        total_tests_in_repo=total,
        fallback_used=result.fallback_used,
        fallback_reason=result.fallback_reason,
        confidence=result.confidence,
        instrumented=instrumented,
        evidence_fresh=evidence_fresh,
    )

    next_actions: List[str] = []
    if result.run_commands:
        next_actions.extend(result.run_commands)
    if result.fallback_used:
        next_actions.append("run the full test suite (no reusable mappings found)")
    if safety:
        next_actions.append(
            f"consider the full suite: {result.total_affected_tests}/{total} tests affected (>30%)"
        )

    summary = _deterministic_summary(result, ratio, safety)
    if llm is not None:
        try:
            text = (llm(evaluate_messages(context)) or "").strip()
            if text:
                summary = text
        except Exception:  # noqa: BLE001 - never fail the run on an LLM hiccup
            pass

    return Evaluation(
        confidence=result.confidence,
        fallback_used=result.fallback_used,
        safety_flag=safety,
        impacted_ratio=ratio,
        summary=summary,
        next_actions=next_actions,
    )


def _deterministic_summary(result: TiaResult, ratio: Optional[float], safety: bool) -> str:
    if result.fallback_used:
        base = (
            f"No reusable test mappings were found for {result.repo}#{result.pr_number} "
            f"({result.files_analyzed} file(s) analyzed). "
            + (result.fallback_reason or "Run the full suite.")
        )
    else:
        base = (
            f"Found {result.total_affected_tests} affected test(s) for "
            f"{result.repo}#{result.pr_number} across {result.files_analyzed} changed file(s) "
            f"(confidence: {result.confidence})."
        )
    if safety and ratio is not None:
        base += f" That is {ratio:.0%} of the suite — a full run is recommended."
    return base