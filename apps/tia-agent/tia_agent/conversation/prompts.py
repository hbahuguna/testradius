"""Prompt builders for the LLM-guided flow.

All builders embed ``SYSTEM_PROMPT`` and are fed only D11-safe contexts
(see :mod:`tia_agent.conversation.context`). Replies that must be structured
are JSON; :func:`parse_json_object` tolerates fenced or chatty output.
"""

from __future__ import annotations

import ast
import json
from typing import Any, Dict, List, Mapping, Optional

from .context import assert_d11_safe

Message = Dict[str, str]

SYSTEM_PROMPT = """\
You are tia-agent, a Test Impact Analysis assistant running locally on the user's machine.
You guide the flow: collect missing inputs, explain each step, and summarize results.

Rules:
1. Evidence-first: results come only from the TestRadius tools. NEVER invent or guess tests.
2. Ask, don't assume: request required inputs you don't have (repo, PR number).
3. Explain before acting: never run instrumentation without explicit user approval.
4. Privacy: you receive only changed file paths, selected symbol names, and counts.
   Never ask for repo code, diffs, or file contents.
5. Read-only: never modify the user's code.
6. Be concise. Ground every statement in the provided context; do not fabricate numbers.
"""

STEP_LABELS = {
    "license": "license check (activation, daily validation, offline grace)",
    "project": "resolving the TestRadius project for the repo",
    "files": "determining the PR's changed source files",
    "evidence": "checking whether TestRadius evidence is fresh",
    "instrumentation": "running instrumentation to refresh evidence",
    "analyze": "running Test Impact Analysis against the evidence graph",
    "evaluate": "evaluating the result (coverage, confidence, safety)",
    "meter": "recording the run against your license quota",
}


_KNOWN_SLOT_KEYS = ("repo", "pr_number", "commit_sha")


def slots_messages(user_text: str, known: Mapping[str, Any]) -> List[Message]:
    # Only the intake slots ever travel to the LLM — never arbitrary keys.
    safe_known = {k: known[k] for k in _KNOWN_SLOT_KEYS if k in known}
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Extract the TIA request parameters from the message. "
                "Respond with JSON only, keys: repo (string, owner/repo or URL), "
                "pr_number (integer), commit_sha (string, optional). "
                "Omit keys you cannot determine. Do not guess.\n\n"
                f"Already known: {json.dumps(safe_known)}\n"
                f"Message: {user_text!r}"
            ),
        },
    ]


def explain_messages(step: str, context: Mapping[str, Any]) -> List[Message]:
    # Enforced at the boundary: the facts embedded in the prompt must be D11-safe.
    assert_d11_safe(context)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"In one or two short sentences, explain to the user that you are about to: "
                f"{STEP_LABELS.get(step, step)}. "
                f"Use only these facts: {json.dumps(dict(context))}. "
                "Do not add numbers or claims not present in the facts."
            ),
        },
    ]


def evaluate_messages(context: Mapping[str, Any]) -> List[Message]:
    # Enforced at the boundary: the facts embedded in the prompt must be D11-safe.
    assert_d11_safe(context)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Summarize the TIA result for the user in 2-4 sentences and suggest next "
                "actions (e.g. run the listed test commands, consider the full suite). "
                "Ground everything in these facts — do not invent tests or counts: "
                f"{json.dumps(dict(context))}"
            ),
        },
    ]


def parse_json_object(text: Optional[str]) -> Dict[str, Any]:
    """Best-effort JSON object extraction from a possibly-chatty LLM reply."""
    if not text:
        return {}
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    # Find the first balanced {...} block.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    candidate = cleaned[start:end + 1] if start != -1 and end > start else cleaned
    for parse in (json.loads, ast.literal_eval):
        try:
            obj = parse(candidate)
            if isinstance(obj, dict):
                return obj
        except (ValueError, SyntaxError):
            continue
    return {}