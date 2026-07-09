from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional, Set

import logging
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from testsquad_workbench.sdet_procedure.inference.session_manager import SessionManager
from testsquad_workbench.sdet_procedure.inference.conversation_state import ConversationState
from testsquad_workbench.main import proxy_router

logger = logging.getLogger(__name__)


MODEL_PATH = os.environ.get("SDET_MODEL_PATH")
BASE_MODEL = os.environ.get("SDET_BASE_MODEL", "Qwen/Qwen3-8B")
SESSION_CONTEXT_API = os.environ.get("SESSION_CONTEXT_API", "http://localhost:9800")
OPENCODE_SESSION_ID = os.environ.get("OPENCODE_SESSION_ID", "").strip()
MANAGER = SessionManager(model_path=MODEL_PATH, base_model=BASE_MODEL)


async def _push_session_context(path: str, data: dict) -> None:
    """Fire-and-forget push to the session context engine. Failures are silent."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            await c.post(f"{SESSION_CONTEXT_API}{path}", json=data)
    except Exception:
        pass


async def _send_ws_json(ws_set: set, data: dict) -> None:
    """Send JSON to all WebSocket connections in a session set."""
    dead = set()
    for ws in ws_set:
        try:
            await ws.send_json(data)
        except Exception:
            dead.add(ws)
    for ws in dead:
        ws_set.discard(ws)


def _build_sdet_prompt(state: ConversationState) -> str:
    """Build a prompt for the Qwen SDET model from the full session context (N0-N13 data)."""
    lines: list[str] = []
    lines.append("You are an expert SDET. Generate a production-quality Playwright test for the following scenario.")
    lines.append("")
    lines.append(f"URL: {state.url}")
    lines.append(f"Feature: {state.feature_type or 'unspecified'}")
    lines.append(f"Test Type: {state.test_type or 'positive'}")
    lines.append(f"Scenario: {state.scenario_description or 'User flow test'}")
    lines.append("")

    if state.selected_elements:
        lines.append("Target Elements (N9-N10):")
        for i, el in enumerate(state.selected_elements, 1):
            tag = el.get("tag", "?")
            text = el.get("text", "") or el.get("label", "") or ""
            css = el.get("css_path", el.get("cssPath", ""))
            role = el.get("role", "")
            aria = el.get("aria_label", "")
            lines.append(f"  {i}. <{tag}> text=\"{text}\" css=\"{css}\" role=\"{role}\" aria=\"{aria}\"")
        lines.append("")

    if state.recorded_actions:
        lines.append("Recorded User Actions (N11):")
        for a in state.recorded_actions:
            loc = a.locator or ""
            label = a.label or a.text[:40] or a.tag
            val = a.value or ""
            lines.append(f"  {a.step_order}. {a.action_type} on \"{label}\"  → {loc}  value=\"{val}\"")
        lines.append("")

    lines.append("Generate a complete Playwright test in TypeScript.")
    lines.append("- Use accessible locators (getByRole, getByLabel, getByPlaceholder, getByText)")
    lines.append("- Include proper assertions at each step (URL checks, visibility checks, value checks)")
    lines.append("- Use realistic test data (not 'test-value')")
    lines.append("- Use page.goto() for navigation")
    lines.append("- Handle async with await")
    lines.append("- Import test and expect from '@playwright/test'")
    lines.append("")
    lines.append("Output ONLY valid TypeScript code inside a single code block. No explanation.")

    return "\n".join(lines)


async def _generate_test_via_qwen(session_id: str, state: ConversationState) -> str:
    """Call the SDET agent's Qwen model to generate test code from full session context."""
    prompt = _build_sdet_prompt(state)
    try:
        async with httpx.AsyncClient(timeout=90.0) as c:
            resp = await c.post(
                f"{SESSION_CONTEXT_API}/api/qwen/infer",
                json={"prompt": prompt, "max_tokens": 2048, "temperature": 0.3},
            )
        if resp.status_code == 200:
            return (resp.json().get("response", "") or "").strip()
    except httpx.RequestError as e:
        logger.error("Qwen inference failed: %s", e)
        return f"[Qwen HTTP error: {e}]"
    except Exception as e:
        logger.error("Unknown error during Qwen inference: %s", e)
        return f"[Qwen unknown error: {e}]"
    return ""


async def _generate_test_via_opencode(
    session_id: str, state: ConversationState, model: Optional[str]
) -> Dict[str, Any]:
    """Call the OpenCode bridge (apps/testradius/server) to generate test code.

    Returns the parsed response: {"model", "events", "code"}.
    """
    prompt = _build_sdet_prompt(state)
    try:
        async with httpx.AsyncClient(timeout=300.0) as c:
            resp = await c.post(
                f"{SESSION_CONTEXT_API}/api/opencode/run",
                json={"prompt": prompt, "model": model or None, "session_id": session_id},
            )
            if resp.status_code == 200:
                return resp.json()
    except httpx.RequestError as e:
        logger.error("OpenCode run request failed: %s", e)
    except Exception as e:  # pragma: no cover - defensive
        logger.error("Unknown error during OpenCode run: %s", e)
    return {}


async def _stream_opencode_events(session_id: str, session, fallback_code: str = "") -> None:
    """Stream real OpenCode events through WebSocket once the session reaches N14."""
    ws = session.ws_connections
    if not ws:
        return

    state = session.state

    await _send_ws_json(ws, {
        "type": "opencode_event", "event": "thinking",
        "content": (
            f"Analyzing session context: {len(state.recorded_actions)} recorded actions, "
            f"{len(state.selected_elements)} selected elements, "
            f"feature={state.feature_type or '?'}, type={state.test_type or '?'}"
        ),
    })
    await asyncio.sleep(0.2)

    await _send_ws_json(ws, {
        "type": "opencode_event", "event": "text",
        "content": "Calling Provider/Model with full session context (N0-N14)...",
    })

    result = await _generate_test_via_opencode(session_id, state, session.opencode_model)
    events = result.get("events", []) or []

    final_code = ""
    accumulated = ""
    for evt in events:
        etype = evt.get("type")
        if etype == "text":
            content = evt.get("content", "")
            accumulated += content
            final_code = accumulated
            await _send_ws_json(ws, {
                "type": "opencode_code_chunk",
                "content": content,
                "accumulated": accumulated,
            })
            await _send_ws_json(ws, {
                "type": "opencode_event", "event": "text", "content": content,
            })
        elif etype == "tool_use":
            inp = evt.get("input", {}) or {}
            await _send_ws_json(ws, {
                "type": "opencode_event", "event": "tool_use",
                "tool": evt.get("tool", ""),
                "status": evt.get("status", ""),
                "path": inp.get("path", ""),
                "command": inp.get("command", ""),
                "file_content": inp.get("content") or inp.get("file_content", ""),
                "output": evt.get("output", ""),
            })
        elif etype == "error":
            await _send_ws_json(ws, {
                "type": "opencode_error", "content": evt.get("content", "OpenCode error"),
            })

    if not final_code.strip():
        await _send_ws_json(ws, {
            "type": "opencode_event", "event": "text",
            "content": "OpenCode unavailable, falling back to Qwen model.",
        })
        fallback_text = await _generate_test_via_qwen(session_id, state)
        if fallback_text.strip():
            final_code = fallback_text
        else:
            final_code = fallback_code

    if final_code:
        await _push_session_context("/api/session/test-code", {
            "session_id": session_id,
            "code": final_code,
            "language": "typescript",
            "description": "OpenCode-generated test from workbench session",
        })

    await _send_ws_json(ws, {
        "type": "opencode_event", "event": "tool_use",
        "tool": "write",
        "path": "tests/e2e/test_session.py",
        "file_content": final_code,
        "status": "completed",
    })

    await _send_ws_json(ws, {
        "type": "opencode_complete",
        "test_code": final_code,
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
    opencode_model: Optional[str] = None


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

app.include_router(proxy_router)


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
        opencode_session_id=OPENCODE_SESSION_ID, # Pass OpenCode session ID
        opencode_model=req.opencode_model,
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

    tasks = [
        _push_session_context("/api/session/conversation", {"session_id": session_id, "role": "user", "content": req.content}),
    ]
    if result.get("message"):
        tasks.append(_push_session_context("/api/session/conversation", {
            "session_id": session_id,
            "role": result["message"].get("role", "assistant"),
            "content": result["message"].get("content", ""),
        }))
    if req.selected_elements:
        for el in req.selected_elements:
            tasks.append(_push_session_context("/api/session/select-element", {
                "session_id": session_id,
                "tag": el.get("tag", ""),
                "text": el.get("text", ""),
                "selector": el.get("cssPath", el.get("css_path", el.get("selector", ""))),
            }))
    if req.recorded_actions:
        for a in req.recorded_actions:
            tasks.append(_push_session_context("/api/session/record-action", {
                "session_id": session_id,
                "action_type": a.get("action_type", ""),
                "selector": a.get("css_path", ""),
                "value": a.get("value", ""),
            }))
    if tasks:
        await asyncio.gather(*tasks)

    if result.get("next_node") == "N14":
        s = MANAGER.get_session(session_id)
        if s is not None:
            asyncio.create_task(
                _stream_opencode_events(
                    session_id=session_id,
                    session=s,
                    fallback_code=result.get("test_code", ""),
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

                if result.get("next_node") == "N14":
                    asyncio.create_task(
                        _stream_opencode_events(
                            session_id=session_id,
                            session=session,
                            fallback_code=result.get("test_code", ""),
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
