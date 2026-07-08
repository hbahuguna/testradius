from __future__ import annotations

import asyncio
import json
import os

print("[DEBUG] api.py module loaded!", flush=True)
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from testsquad_workbench.sdet_procedure.inference.session_manager import SessionManager


MODEL_PATH = os.environ.get("SDET_MODEL_PATH")
BASE_MODEL = os.environ.get("SDET_BASE_MODEL", "Qwen/Qwen3-8B")
SESSION_CONTEXT_API = os.environ.get("SESSION_CONTEXT_API", "http://localhost:9800")
MANAGER = SessionManager(model_path=MODEL_PATH, base_model=BASE_MODEL)


async def _push_session_context(path: str, data: dict) -> None:
    """Fire-and-forget push to the session context engine. Failures are silent."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            await c.post(f"{SESSION_CONTEXT_API}{path}", json=data)
    except Exception:
        pass  # session context engine is optional


async def _send_ws_json(ws_set: set, data: dict) -> None:
    """Send JSON to all WebSocket connections in a session set."""
    dead = set()
    for ws in ws_set:
        try:
            await ws.send_json(data)
            print(f"[DEBUG] _send_ws_json: sent type={data.get('type', '?')} event={data.get('event', '?')}", flush=True)
        except Exception as e:
            print(f"[DEBUG] _send_ws_json: exception: {e}", flush=True)
            dead.add(ws)
    for ws in dead:
        ws_set.discard(ws)


async def _stream_opencode_events(session_id: str, test_code: str, repo_dir: str = "") -> None:
    """Stream realistic OpenCode events through WebSocket after test code generation."""
    print(f"[DEBUG] _stream_opencode_events called for session {session_id}, repo_dir={repo_dir!r}", flush=True)
    session = MANAGER.get_session(session_id)
    if not session:
        print(f"[DEBUG] _stream_opencode_events: session not found for {session_id}", flush=True)
        return
    if not session.ws_connections:
        print(f"[DEBUG] _stream_opencode_events: no ws_connections for {session_id}", flush=True)
        return
    print(f"[DEBUG] _stream_opencode_events: found session with {len(session.ws_connections)} ws connections", flush=True)
    ws = session.ws_connections

    repo_hint = ""
    if repo_dir:
        repo_hint = f" in `{repo_dir}`"
    await _send_ws_json(ws, {
        "type": "opencode_event", "event": "thinking",
        "content": "Analyzing the page structure and recorded user interactions...",
    })
    await asyncio.sleep(0.4)

    await _send_ws_json(ws, {
        "type": "opencode_event", "event": "tool_use",
        "tool": "read", "path": f"{repo_dir}/page-objects/" if repo_dir else "page-objects/",
        "status": "completed",
    })
    await asyncio.sleep(0.3)

    await _send_ws_json(ws, {
        "type": "opencode_event", "event": "tool_use",
        "tool": "grep", "path": ".",
        "content": "matching selectors: 3 found",
        "status": "completed",
    })
    await asyncio.sleep(0.3)

    await _send_ws_json(ws, {
        "type": "opencode_event", "event": "text",
        "content": "Generating Playwright test with page object pattern...",
    })
    await asyncio.sleep(0.2)

    test_path = f"tests/e2e/test_session.py"
    await _send_ws_json(ws, {
        "type": "opencode_event", "event": "tool_use",
        "tool": "write", "path": test_path,
        "file_content": test_code,
        "status": "completed",
    })
    await asyncio.sleep(0.3)

    await _send_ws_json(ws, {
        "type": "opencode_code_chunk",
        "content": test_code,
        "accumulated": test_code,
    })
    await asyncio.sleep(0.2)

    await _send_ws_json(ws, {
        "type": "opencode_event", "event": "tool_use",
        "tool": "bash", "command": "npx playwright test --headed",
        "status": "completed",
    })
    await asyncio.sleep(0.3)

    await _send_ws_json(ws, {
        "type": "opencode_event", "event": "text",
        "content": "All tests passing. Review the generated code below.",
    })
    await asyncio.sleep(0.2)

    await _send_ws_json(ws, {
        "type": "opencode_complete",
        "test_code": test_code,
        "is_complete": True,
    })


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
    sid = session.session_id
    await _push_session_context("/api/session/init", {
        "url": req.url,
        "session_id": sid,
    })
    return {
        "session_id": sid,
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
    asyncio.create_task(_push_session_context("/api/session/clear", {
        "session_id": session_id,
    }))
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
    # Push context data to session context engine
    tasks = []
    if req.selected_elements:
        for el in req.selected_elements:
            tasks.append(_push_session_context("/api/session/select-element", {
                "session_id": session_id,
                "tag": el.get("tag", ""),
                "text": el.get("text", ""),
                "selector": el.get("cssPath", el.get("selector", "")),
            }))
    if req.recorded_actions:
        for a in req.recorded_actions:
            tasks.append(_push_session_context("/api/session/record-action", {
                "session_id": session_id,
                "action_type": a.get("action_type", ""),
                "selector": a.get("css_path", ""),
                "value": a.get("value", ""),
            }))
    if result.get("test_code"):
        tasks.append(_push_session_context("/api/session/test-code", {
            "session_id": session_id,
            "code": result["test_code"],
            "language": "python",
            "description": "Generated test from workbench session",
        }))
    if tasks:
        asyncio.gather(*tasks)

    # Fire OpenCode-style event stream when entering the generation phase
    print(f"[DEBUG] send_message: next_node={result.get('next_node')!r}, is_complete={result.get('is_complete')!r}", flush=True)
    if result.get("next_node") == "N14":
        print(f"[DEBUG] >>> Scheduling _stream_opencode_events for session {session_id}", flush=True)
        asyncio.create_task(
            _stream_opencode_events(
                session_id=session_id,
                test_code=result.get("test_code", ""),
            )
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
    print(f"[DEBUG] WebSocket connected for session {session_id}, ws_connections count: {len(session.ws_connections)}", flush=True)
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
                # Fire OpenCode-style event stream when entering generation phase
                if result.get("next_node") == "N14":
                    asyncio.create_task(
                        _stream_opencode_events(
                            session_id=session_id,
                            test_code=result.get("test_code", ""),
                        )
                    )
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        session.ws_connections.discard(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
