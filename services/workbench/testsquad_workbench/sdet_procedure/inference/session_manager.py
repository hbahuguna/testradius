from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from testsquad_workbench.sdet_procedure.inference.conversation_state import (
    ConversationState,
    Turn,
    StateSnapshot,
)
from testsquad_workbench.sdet_procedure.inference.inference import (
    SDETInference,
    InferenceConfig,
)
from testsquad_workbench.sdet_procedure.inference.repo_scanner import (
    RepoScanner,
    RepoContext,
)


@dataclass
class Session:
    session_id: str
    state: ConversationState
    inference: Optional[SDETInference] = None
    model_loaded: bool = False
    repo_context: Optional[RepoContext] = None
    ws_connections: Set[Any] = field(default_factory=set)
    opencode_session_id: str = "" # Add opencode_session_id to Session
    opencode_model: Optional[str] = None

    @property
    def url(self) -> str:
        return self.state.url

    @property
    def current_node(self) -> str:
        return self.state.current_node_id

    @property
    def messages(self) -> List[Dict[str, str]]:
        return [
            {"role": t.role, "content": t.content}
            for t in self.state.history
        ]

    @property
    def suggestion_chips(self) -> List[Dict]:
        return self.state.get_suggestion_chips()

    @property
    def snapshot(self) -> StateSnapshot:
        return self.state.snapshot()


class SessionManager:
    def __init__(self, model_path: Optional[str] = None, base_model: str = "Qwen/Qwen3-8B"):
        self._sessions: Dict[str, Session] = {}
        self._model_path = model_path
        self._base_model = base_model
        self._shared_inference: Optional[SDETInference] = None
        self._inference_loaded = False

    def create_session(
        self,
        url: str,
        elements: Optional[List[Dict]] = None,
        load_model: bool = False,
        automation_repo: Optional[str] = None,
        opencode_session_id: str = "", # New parameter
        opencode_model: Optional[str] = None,
    ) -> Session:
        state = ConversationState(url=url, elements=elements)
        state.inject_welcome()

        inference = None
        model_loaded = False
        if load_model and self._model_path:
            inference = self._load_inference()
            model_loaded = inference is not None

        repo_context = None
        if automation_repo:
            scanner = RepoScanner(automation_repo)
            repo_context = scanner.scan()
            if repo_context.is_empty():
                print(f"Warning: No page objects or utilities found in {automation_repo}")

        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            state=state,
            inference=inference,
            model_loaded=model_loaded,
            repo_context=repo_context,
            opencode_session_id=opencode_session_id, # Pass to Session constructor
            opencode_model=opencode_model,
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def delete_session(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    def list_sessions(self) -> List[Dict[str, Any]]:
        return [
            {
                "session_id": s.session_id,
                "url": s.url,
                "current_node": s.current_node,
                "total_turns": s.state.total_turns,
                "is_complete": s.state.is_terminal(),
            }
            for s in self._sessions.values()
        ]

    def reset_session(self, session_id: str, node_id: str) -> Optional[Dict[str, Any]]:
        session = self.get_session(session_id)
        if not session:
            return None
        if not session.state.reset_to_node(node_id):
            return None
        return {
            "messages": session.messages,
            "current_node": session.current_node,
            "suggestion_chips": session.suggestion_chips,
            "snapshot": {
                "total_turns": session.state.total_turns,
                "clarify_count": session.state.clarify_count,
                "revise_count": session.state.revise_count,
                "feature_type": session.state.feature_type,
                "test_type": session.state.test_type,
                "is_complete": session.state.is_terminal(),
            },
        }

    def process_message(
        self,
        session_id: str,
        content: str,
        selected_elements: Optional[List[Dict]] = None,
        recorded_actions: Optional[List[Dict]] = None,
        use_model: bool = False,
    ) -> Dict[str, Any]:
        session = self.get_session(session_id)
        if not session:
            return {"type": "error", "content": "Session not found"}

        if not session.state.can_handle_user_input():
            return {"type": "error", "content": "Session is already complete. Start a new session."}

        result = session.state.process_user_input(content, selected_elements, recorded_actions)

        if use_model and session.inference and session.model_loaded:
            try:
                model_output = self._generate_with_model(session, content)
                result["message"]["content"] = model_output
            except Exception as e:
                result["message"]["content"] = result["message"]["content"]

        if result["is_complete"] or result["next_node"] == "N14":
            try:
                test_code = session.state.generate_test_code()
                result["test_code"] = test_code
            except Exception:
                pass

        return {
            "type": "agent_response",
            "message": result["message"],
            "next_node": result["next_node"],
            "suggestion_chips": result["suggestion_chips"],
            "is_complete": result["is_complete"],
            "test_code": result.get("test_code"),
            "session_snapshot": {
                "total_turns": session.state.total_turns,
                "clarify_count": session.state.clarify_count,
                "revise_count": session.state.revise_count,
                "feature_type": session.state.feature_type,
                "test_type": session.state.test_type,
            },
        }

    def scrape_page(self, url: str, timeout_ms: int = 30000) -> Dict[str, Any]:
        try:
            import asyncio
            from testsquad_workbench.sdet_procedure.inference.page_scraper import PageScraper

            async def _scrape():
                async with PageScraper(timeout_ms=timeout_ms) as scraper:
                    snap = await scraper.scrape(url)
                    return snap

            snap = asyncio.run(_scrape())
            return {
                "url": snap.url,
                "title": snap.title,
                "elements": [{
                    "id": f"{el.tag}-{i}",
                    "tag": el.tag,
                    "type": el.type,
                    "label": el.label,
                    "id_attr": el.id,
                    "name": el.name,
                    "role": el.role,
                    "placeholder": el.placeholder,
                    "text": el.text,
                    "href": el.href,
                    "aria_label": el.aria_label,
                } for i, el in enumerate(snap.elements)],
                "a11y_tree": snap.a11y_tree,
                "viewport": snap.viewport,
                "text_content": snap.text_content,
            }
        except Exception as e:
            return {"error": str(e)}

    def _load_inference(self) -> Optional[SDETInference]:
        if self._inference_loaded and self._shared_inference:
            return self._shared_inference
        try:
            config = InferenceConfig(
                model_path=self._model_path,
                base_model_name=self._base_model,
            )
            engine = SDETInference(config)
            engine.load()
            self._shared_inference = engine
            self._inference_loaded = True
            return engine
        except Exception as e:
            print(f"Failed to load model: {e}")
            return None

    def _generate_with_model(self, session: Session, user_input: str) -> str:
        if not session.inference or not session.model_loaded:
            return session.state.get_agent_response()

        system_prompt = "You are an expert Senior SDET. Given automation repo context and a test scenario, output only the Playwright test code. Be concise. No reasoning, no explanation."

        scenario = user_input
        if session.state.scenario_description:
            scenario = f"{session.state.scenario_description}\n\nCurrent request: {user_input}"

        response = session.inference.generate(
            scenario=scenario,
            system_prompt=system_prompt,
            repo_context=session.repo_context,
        )
        return response
