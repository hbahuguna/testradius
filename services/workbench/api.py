from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from testsquad_workbench.sdet_procedure.inference.session_manager import SessionManager


MODEL_PATH = os.environ.get("SDET_MODEL_PATH")
BASE_MODEL = os.environ.get("SDET_BASE_MODEL", "Qwen/Qwen3-8B")
MANAGER = SessionManager(model_path=MODEL_PATH, base_model=BASE_MODEL)


class ScrapeRequest(BaseModel):
    url: str
    timeout_ms: int = 30000


class SessionStartRequest(BaseModel):
    url: str
    elements: List[Dict[str, Any]] = []
    load_model: bool = False
    automation_repo: Optional[str] = None


class MessageRequest(BaseModel):
    content: str
    selected_elements: Optional[List[Dict[str, Any]]] = None
    recorded_actions: Optional[List[Dict[str, Any]]] = None
    current_node: Optional[str] = None
    use_model: bool = False


class ResetRequest(BaseModel):
    node_id: str


app = FastAPI(title="SDET Workbench API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/workbench/health")
async def health():
    return {"status": "ok", "model_loaded": MANAGER._inference_loaded}


@app.post("/api/workbench/scrape")
async def scrape_page(req: ScrapeRequest):
    result = MANAGER.scrape_page(req.url, req.timeout_ms)
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@app.post("/api/workbench/session/start")
async def start_session(req: SessionStartRequest):
    session = MANAGER.create_session(
        url=req.url,
        elements=req.elements,
        load_model=req.load_model,
        automation_repo=req.automation_repo,
    )
    return {
        "session_id": session.session_id,
        "current_node": session.current_node,
        "messages": session.messages,
        "suggestion_chips": session.suggestion_chips,
        "repo_context": {
            "page_objects": [po.class_name for po in session.repo_context.page_objects] if session.repo_context else [],
            "utilities": [u.name for u in session.repo_context.utilities] if session.repo_context else [],
        } if session.repo_context else None,
        "snapshot": {
            "total_turns": session.state.total_turns,
            "clarify_count": session.state.clarify_count,
            "revise_count": session.state.revise_count,
        },
    }


@app.get("/api/workbench/sessions")
async def list_sessions():
    return MANAGER.list_sessions()


@app.get("/api/workbench/session/{session_id}")
async def get_session(session_id: str):
    session = MANAGER.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session.session_id,
        "current_node": session.current_node,
        "messages": session.messages,
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


@app.delete("/api/workbench/session/{session_id}")
async def delete_session(session_id: str):
    if not MANAGER.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted"}


@app.post("/api/workbench/session/{session_id}/reset")
async def reset_session(session_id: str, req: ResetRequest):
    result = MANAGER.reset_session(session_id, req.node_id)
    if not result:
        raise HTTPException(status_code=404, detail="Session not found or invalid node_id")
    return result


@app.post("/api/workbench/session/{session_id}/message")
async def send_message(session_id: str, req: MessageRequest):
    result = MANAGER.process_message(
        session_id=session_id,
        content=req.content,
        selected_elements=req.selected_elements,
        recorded_actions=req.recorded_actions,
        use_model=req.use_model,
    )
    return result


@app.websocket("/api/workbench/session/{session_id}/ws")
async def session_websocket(websocket: WebSocket, session_id: str):
    await websocket.accept()
    session = MANAGER.get_session(session_id)
    if not session:
        await websocket.send_json({"type": "error", "content": "Session not found"})
        await websocket.close()
        return

    session.ws_connections.add(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "user_message":
                result = MANAGER.process_message(
                    session_id=session_id,
                    content=data.get("content", ""),
                    selected_elements=data.get("selected_elements"),
                    recorded_actions=data.get("recorded_actions"),
                    use_model=data.get("use_model", False),
                )
                await websocket.send_json(result)
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        session.ws_connections.discard(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
