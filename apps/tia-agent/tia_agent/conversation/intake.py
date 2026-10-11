"""Intake Q&A: collect and validate the inputs an analyze run needs.

Parsing is regex-first (deterministic, works with the LLM disabled) and then
LLM-assisted for natural language. The flow keeps asking for missing required
inputs until it has them — required today: ``repo`` and ``pr_number``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .prompts import parse_json_object, slots_messages

# A callable that takes chat messages and returns the assistant's text.
LLMCallable = Callable[[List[Dict[str, str]]], str]

REQUIRED = ("repo", "pr_number")

_GH_URL = re.compile(r"github\.com[/:]([\w.-]+/[\w.-]+?)(?:\.git)?(?:[/\s#?]|$)")
_BARE_REPO = re.compile(r"(?<![\w./-])([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?![\w./-])")
_PR_PATTERNS = [
    re.compile(r"/(?:pull|pulls|pr|merge_requests|mr)/(\d+)\b", re.IGNORECASE),
    re.compile(r"(?:^|\s)#\s*(\d+)"),
    re.compile(r"\bpr\s*#?\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bpull\s*request\s*#?\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bpr[_\s-]?number\s*[=:]?\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"^\s*#?\s*(\d+)\s*$"),  # a bare number, e.g. answering "which PR?"
]
_COMMIT = re.compile(r"\b(?:commit|sha|rev|branch)\s*[:=]?\s*([0-9a-f]{7,40}|[\w./-]{2,})\b", re.IGNORECASE)

_REQUEST_HINTS = re.compile(
    r"analy[sz]e|impact|which tests|what tests|affected tests|\btia\b|\bpr\b", re.IGNORECASE
)


@dataclass
class Slots:
    repo: str = ""
    pr_number: Optional[int] = None
    commit_sha: str = "main"
    file_paths: List[str] = field(default_factory=list)

    def merge(self, other: Dict[str, Any]) -> "Slots":
        if other.get("repo"):
            self.repo = normalize_repo(str(other["repo"]))
        if other.get("pr_number") is not None:
            self.pr_number = _to_int(other["pr_number"])
        if other.get("commit_sha"):
            self.commit_sha = str(other["commit_sha"])
        if other.get("file_paths"):
            self.file_paths = list(other["file_paths"])
        return self

    def as_dict(self) -> Dict[str, Any]:
        return {
            "repo": self.repo,
            "pr_number": self.pr_number,
            "commit_sha": self.commit_sha,
        }


def normalize_repo(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip().strip("`\"'")
    m = re.search(r"github\.com[/:]([\w.-]+/[\w.-]+)", s)
    if m:
        s = m.group(1)
    if s.endswith(".git"):
        s = s[:-4]
    return s.strip("/")


def looks_like_request(text: str) -> bool:
    return bool(_REQUEST_HINTS.search(text or ""))


def parse_slots(text: str, base: Optional[Slots] = None, llm: Optional[LLMCallable] = None) -> Slots:
    slots = Slots()
    if base is not None:
        slots = Slots(repo=base.repo, pr_number=base.pr_number,
                      commit_sha=base.commit_sha, file_paths=list(base.file_paths))

    # 1. deterministic regex pass
    found: Dict[str, Any] = {}
    m = _GH_URL.search(text or "")
    if m:
        found["repo"] = m.group(1)
    else:
        m = _BARE_REPO.search(text or "")
        if m and not m.group(1).lower().startswith(("http", "and/", "or/")):
            found["repo"] = m.group(1)
    for pat in _PR_PATTERNS:
        m = pat.search(text or "")
        if m:
            found["pr_number"] = _to_int(m.group(1))
            break
    m = _COMMIT.search(text or "")
    if m:
        found["commit_sha"] = m.group(1)
    slots.merge(found)

    # 2. LLM pass for anything still missing (natural language)
    if llm is not None and _still_missing(slots):
        try:
            reply = llm(slots_messages(text, slots.as_dict()))
            slots.merge(parse_json_object(reply))
        except Exception:  # noqa: BLE001 - LLM is best-effort; never block intake
            pass
    return slots


def _still_missing(slots: Slots) -> bool:
    return any(key in REQUIRED for key in missing_slots(slots))


def missing_slots(slots: Slots) -> List[str]:
    missing: List[str] = []
    if not slots.repo:
        missing.append("repo")
    if slots.pr_number is None:
        missing.append("pr_number")
    return missing


def question_for(field_name: str) -> str:
    return {
        "repo": "Which repository should I analyze? (owner/repo or a GitHub URL)",
        "pr_number": "Which PR number should I analyze?",
    }.get(field_name, f"Please provide {field_name}.")


def validate(slots: Slots) -> List[str]:
    errors: List[str] = []
    if not slots.repo:
        errors.append("repo is required")
    elif not re.match(r"^[\w.-]+/[\w.-]+$", slots.repo):
        errors.append(f"repo '{slots.repo}' must look like owner/repo")
    if slots.pr_number is None:
        errors.append("pr_number is required")
    elif slots.pr_number <= 0:
        errors.append("pr_number must be a positive integer")
    return errors


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip().lstrip("#"))
    except (TypeError, ValueError):
        return None