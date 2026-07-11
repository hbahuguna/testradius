"""Session-context tools (core, in-memory).

Mirrors the existing SDET session model (apps/testradius/server/
session_context.py) so the standalone agent can record actions, track
selected elements, and retrieve full context — the scratchpad's structured
sibling used to build prompts for code generation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class _Action:
    action_type: str
    selector: str
    value: str = ""
    url: str = ""


@dataclass
class _Session:
    session_id: str
    url: str = ""
    actions: list[_Action] = field(default_factory=list)
    elements: list[dict[str, Any]] = field(default_factory=list)
    test_code: str = ""


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, _Session] = {}

    def init(self, url: str = "", session_id: str = "") -> str:
        sid = session_id or uuid.uuid4().hex[:8]
        self._sessions[sid] = _Session(session_id=sid, url=url)
        return sid

    def record_action(self, session_id: str, action_type: str, selector: str, value: str = "", url: str = "") -> bool:
        s = self._sessions.get(session_id)
        if not s:
            return False
        s.actions.append(_Action(action_type, selector, value, url or s.url))
        return True

    def context(self, session_id: str) -> Optional[dict[str, Any]]:
        s = self._sessions.get(session_id)
        if not s:
            return None
        return {
            "session_id": s.session_id,
            "url": s.url,
            "recorded_actions": [
                {"action_type": a.action_type, "selector": a.selector, "value": a.value, "url": a.url}
                for a in s.actions
            ],
            "selected_elements": s.elements,
            "test_code": s.test_code,
        }


_store = SessionStore()


def session_init(url: str = "", session_id: str = "") -> str:
    return _store.init(url=url, session_id=session_id)


def session_record_action(session_id: str, action_type: str, selector: str, value: str = "", url: str = "") -> bool:
    return _store.record_action(session_id, action_type, selector, value, url)


def session_context(session_id: str) -> dict[str, Any]:
    ctx = _store.context(session_id)
    return ctx or {"error": f"session {session_id} not found"}
