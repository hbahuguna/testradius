import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .log_config import get_logger

logger = get_logger("session")


@dataclass
class RecordedAction:
    action_type: str  # click | type | select | navigate | hover
    selector: str
    value: str = ""
    url: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class SelectedElement:
    tag: str
    text: str = ""
    selector: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class GeneratedTestCode:
    code: str = ""
    language: str = ""
    description: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class SessionContext:
    session_id: str
    url: str = ""
    recorded_actions: list[RecordedAction] = field(default_factory=list)
    selected_elements: list[SelectedElement] = field(default_factory=list)
    test_code: Optional[GeneratedTestCode] = None
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SessionContextManager:
    def __init__(self):
        self._sessions: dict[str, SessionContext] = {}

    def create_session(self, url: str = "", session_id: str = "") -> str:
        if session_id:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionContext(session_id=session_id, url=url)
                logger.info("Session %s created (from caller)%s", session_id, f"  url={url}" if url else "")
            else:
                logger.debug("Session %s already exists, reusing", session_id)
            return session_id
        session_id = str(uuid.uuid4())[:8]
        self._sessions[session_id] = SessionContext(session_id=session_id, url=url)
        logger.info("Session %s created%s", session_id, f"  url={url}" if url else "")
        return session_id

    def get_session(self, session_id: str) -> Optional[SessionContext]:
        session = self._sessions.get(session_id)
        if session is None:
            logger.warning("Session %s not found", session_id)
        return session

    def delete_session(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info("Session %s deleted", session_id)
            return True
        return False

    def clear_session(self, session_id: str) -> bool:
        session = self.get_session(session_id)
        if session is None:
            return False
        session.recorded_actions.clear()
        session.selected_elements.clear()
        session.test_code = None
        session.conversation_history.clear()
        session.metadata.clear()
        session.updated_at = datetime.now(timezone.utc).isoformat()
        logger.info("Session %s cleared", session_id)
        return True

    def record_action(
        self,
        session_id: str,
        action_type: str,
        selector: str,
        value: str = "",
        url: str = "",
    ) -> bool:
        session = self.get_session(session_id)
        if session is None:
            return False
        for existing in session.recorded_actions:
            if (existing.action_type == action_type
                    and existing.selector == selector
                    and existing.value == value):
                logger.debug(
                    "Session %s: skip duplicate %s on %s",
                    session_id, action_type, selector,
                )
                return True
        action = RecordedAction(
            action_type=action_type,
            selector=selector,
            value=value,
            url=url or session.url,
        )
        session.recorded_actions.append(action)
        session.updated_at = datetime.now(timezone.utc).isoformat()
        logger.debug(
            "Session %s: recorded %s on %s%s",
            session_id, action_type, selector,
            f"  value={value}" if value else "",
        )
        return True

    def select_element(
        self,
        session_id: str,
        tag: str,
        text: str = "",
        selector: str = "",
        attributes: Optional[dict[str, str]] = None,
    ) -> bool:
        session = self.get_session(session_id)
        if session is None:
            return False
        element = SelectedElement(
            tag=tag,
            text=text,
            selector=selector,
            attributes=attributes or {},
        )
        session.selected_elements.append(element)
        session.updated_at = datetime.now(timezone.utc).isoformat()
        preview = text[:60] if text else selector[:60]
        logger.debug("Session %s: selected <%s>  %s", session_id, tag, preview)
        return True

    def set_test_code(
        self,
        session_id: str,
        code: str,
        language: str = "",
        description: str = "",
    ) -> bool:
        session = self.get_session(session_id)
        if session is None:
            return False
        session.test_code = GeneratedTestCode(
            code=code,
            language=language,
            description=description,
        )
        session.updated_at = datetime.now(timezone.utc).isoformat()
        logger.info(
            "Session %s: test code updated (%d bytes, %s)",
            session_id, len(code), language or "?",
        )
        return True

    def add_message(self, session_id: str, role: str, content: str) -> bool:
        session = self.get_session(session_id)
        if session is None:
            return False
        session.conversation_history.append({"role": role, "content": content})
        session.updated_at = datetime.now(timezone.utc).isoformat()
        logger.debug("Session %s: added %s message (%d chars)", session_id, role, len(content))
        return True

    def to_dict(self, session_id: str) -> Optional[dict[str, Any]]:
        session = self.get_session(session_id)
        if session is None:
            return None
        return {
            "session_id": session.session_id,
            "url": session.url,
            "recorded_actions": [
                {
                    "action_type": a.action_type,
                    "selector": a.selector,
                    "value": a.value,
                    "url": a.url,
                    "timestamp": a.timestamp,
                }
                for a in session.recorded_actions
            ],
            "selected_elements": [
                {
                    "tag": e.tag,
                    "text": e.text,
                    "selector": e.selector,
                    "attributes": e.attributes,
                    "timestamp": e.timestamp,
                }
                for e in session.selected_elements
            ],
            "test_code": {
                "code": session.test_code.code,
                "language": session.test_code.language,
                "description": session.test_code.description,
                "timestamp": session.test_code.timestamp,
            }
            if session.test_code
            else None,
            "conversation_history": session.conversation_history,
            "metadata": session.metadata,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }
