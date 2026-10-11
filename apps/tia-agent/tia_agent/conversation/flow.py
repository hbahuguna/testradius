"""LLM-guided conversational flow (A3).

Orchestrates: intake Q&A -> step explanations -> instrumentation gate ->
analyze -> result evaluation. Every dependency is injectable so the whole flow
is unit-testable and works with the LLM disabled (deterministic templates).

D10: instrumentation is NEVER run automatically — the flow explains and asks.
D11: explanations/evaluations are fed only D11-safe contexts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Protocol

from ..analyze import AnalyzeRunner, TiaResult
from ..config import TiaConfig
from ..errors import GitHubAuthError, GitHubError, TiaError
from .context import build_context
from .evaluate import Evaluation, evaluate
from .intake import (
    LLMCallable,
    Slots,
    missing_slots,
    parse_slots,
    question_for,
    validate,
)
from .prompts import STEP_LABELS, explain_messages
from .toolbox import Evidence, RadiusToolbox, Toolbox


class UI(Protocol):
    def say(self, message: str) -> None: ...
    def ask(self, prompt: str) -> str: ...
    def confirm(self, prompt: str) -> bool: ...


EXPLAIN_FALLBACK = {
    "license": "Checking your license and remaining quota…",
    "project": "Resolving the TestRadius project for this repo…",
    "evidence": "Checking whether TestRadius evidence for these files is fresh…",
    "instrumentation": (
        "Evidence is missing or stale. Instrumentation runs the suite with coverage "
        "to refresh the evidence graph, which makes the impact analysis precise. "
        "It is never run automatically — I need your OK first."
    ),
    "analyze": "Running Test Impact Analysis against the evidence graph…",
    "meter": "Recording this run against your license quota.",
}


@dataclass
class FlowResult:
    status: str  # ok | cancelled | error
    slots: Optional[Slots] = None
    result: Optional[TiaResult] = None
    evaluation: Optional[Evaluation] = None
    message: str = ""
    instrumented: bool = False


class ConversationFlow:
    def __init__(
        self,
        config: TiaConfig,
        runner: AnalyzeRunner,
        ui: UI,
        *,
        toolbox: Optional[Toolbox] = None,
        llm: Optional[LLMCallable] = None,
        max_intake_turns: int = 6,
        token_prompt: Optional[Callable[[], Optional[str]]] = None,
        repo_path: Optional[str] = None,
    ):
        self.config = config
        self.runner = runner
        self.ui = ui
        self.toolbox = toolbox if toolbox is not None else RadiusToolbox(runner.radius)
        self.llm = llm
        self.max_intake_turns = max_intake_turns
        # Called only when GitHub needs a token for a private repo/PR.
        self.token_prompt = token_prompt
        # Local checkout for test validation + deterministic fallback (F1).
        self.repo_path = repo_path or getattr(config, "repo_path", "") or None

    # -- public entry -------------------------------------------------------
    def handle(self, text: str) -> FlowResult:
        slots = parse_slots(text, llm=self.llm)
        slots = self._collect_missing(slots)
        if slots is None:
            self.ui.say("Okay, cancelled.")
            return FlowResult("cancelled", message="intake cancelled")

        errors = validate(slots)
        if errors:
            msg = "I still need valid input: " + "; ".join(errors)
            self.ui.say(msg)
            return FlowResult("error", slots=slots, message=msg)

        # Gate before the quota-consuming run.
        if not self.ui.confirm(
            f"Run TIA on {slots.repo}#{slots.pr_number}? This uses one license quota unit. [y/N] "
        ):
            self.ui.say("Cancelled.")
            return FlowResult("cancelled", slots=slots, message="run not confirmed")

        try:
            return self._run(slots)
        except TiaError as e:
            self.ui.say(f"error: {e}")
            return FlowResult("error", slots=slots, message=str(e))

    # -- intake Q&A ---------------------------------------------------------
    def _collect_missing(self, slots: Slots) -> Optional[Slots]:
        for _ in range(self.max_intake_turns):
            missing = missing_slots(slots)
            if not missing:
                break
            answer = self.ui.ask(question_for(missing[0])).strip()
            if not answer:
                return None
            slots = parse_slots(answer, base=slots, llm=self.llm)
        else:
            # ran out of turns with inputs still missing
            if missing_slots(slots):
                return None
        return slots

    # -- the run ------------------------------------------------------------
    def _run(self, slots: Slots) -> FlowResult:
        repo, pr = slots.repo, int(slots.pr_number)
        files = self._resolve_files(repo, pr, slots.file_paths or None)

        self._explain("license")
        self.runner.ensure_license()

        self._explain("project")
        project = self.runner.resolve(repo)

        instrumented = self._instrumentation_gate(repo, project, files)

        self._explain("analyze", build_context(
            repo=repo, pr_number=pr, changed_file_paths=files))
        started = time.time()
        raw = self.runner.analyze(project, repo, pr, slots.commit_sha, files)
        result = self.runner.to_result(raw, repo, pr, repo_path=self.repo_path,
                                       changed_files=files)

        self._explain("meter")
        self.runner.meter(result, repo, time.time() - started)

        raw_paths = raw.get("pr_files") or raw.get("file_paths") or files or []
        evaluation = evaluate(
            result,
            total_tests_in_repo=result.total_tests_in_repo,
            instrumented=instrumented,
            evidence_fresh=None,
            llm=self.llm,
            changed_file_paths=list(raw_paths),
        )
        self._report(result, evaluation)
        return FlowResult("ok", slots=slots, result=result,
                          evaluation=evaluation, instrumented=instrumented,
                          message=evaluation.summary)

    def _resolve_files(self, repo: str, pr: int, files: Optional[List[str]]) -> Optional[List[str]]:
        """Fetch the PR's changed source files, prompting for a token if needed.

        Failures are non-fatal: the backend can still fetch the PR (it holds its
        own GitHub token), so we continue without a file list.
        """
        if files:
            return files
        try:
            return self.runner.fetch_files(repo, pr) or None
        except GitHubAuthError as e:
            if self.token_prompt is None:
                self.ui.say(f"GitHub needs a token for {repo} ({e}); continuing without a file list.")
                return None
            self.ui.say(f"GitHub needs a token to read files for {repo}.")
            token = self.token_prompt()
            if not token:
                self.ui.say("No token provided — continuing without a file list.")
                return None
            self.runner.set_github_token(token)
            try:
                return self.runner.fetch_files(repo, pr) or None
            except GitHubError as retry_err:
                self.ui.say(f"GitHub still rejected the token ({retry_err}); continuing.")
                return None
        except GitHubError as e:
            self.ui.say(f"Could not fetch PR files ({e}); continuing without a file list.")
            return None

    def _instrumentation_gate(self, repo: str, project, files) -> bool:
        """Explain + ask before instrumentation (D10). Never auto-runs."""
        if self.toolbox is None:
            return False
        evidence: Evidence = self.toolbox.check_evidence(repo, project, files)
        self._explain("evidence", build_context(
            repo=repo, evidence_fresh=evidence.fresh if evidence.known else None))
        if not evidence.needs_instrumentation:
            return False

        self._explain("instrumentation", build_context(repo=repo))
        if not self.ui.confirm(
            f"Run instrumentation for {repo} now? It inspects your tests locally. [y/N] "
        ):
            self.ui.say("Skipping instrumentation — results may be less precise.")
            return False
        self.ui.say("Running instrumentation…")
        result = self.toolbox.run_instrumentation(repo, project, files)
        status = getattr(result, "status", None)
        if getattr(result, "ok", True) and status in (None, "COMPLETED"):
            edges = getattr(result, "edges", 0)
            suffix = f" ({edges} edges)" if edges else ""
            self.ui.say(f"Instrumentation complete{suffix}; evidence refreshed.")
            return True
        error = getattr(result, "error", None) or status or "unknown error"
        self.ui.say(f"Instrumentation did not complete ({error}); continuing with existing evidence.")
        return False

    # -- messaging ----------------------------------------------------------
    def _explain(self, step: str, facts: Optional[dict] = None) -> None:
        text = None
        if self.llm is not None:
            try:
                text = (self.llm(explain_messages(step, facts or {})) or "").strip()
            except Exception:  # noqa: BLE001 - templates are the safety net
                text = None
        self.ui.say(text or EXPLAIN_FALLBACK.get(step, step))

    def _report(self, result: TiaResult, evaluation: Evaluation) -> None:
        self.ui.say(f"Affected tests: {result.total_affected_tests} "
                    f"(confidence: {result.confidence})")
        for t in result.tests:
            self.ui.say(f"  - {t.get('name', '?')}  [{t.get('file', '')}]")
        if result.fallback_used:
            self.ui.say(f"[fallback] {result.fallback_reason}")
        self.ui.say(evaluation.summary)
        for action in evaluation.next_actions:
            self.ui.say(f"  $ {action}" if action.startswith(("pytest", "npx")) else f"  - {action}")