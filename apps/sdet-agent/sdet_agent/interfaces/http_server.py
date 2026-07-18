"""HTTP interface (textbook Ch.3: expose the agent as a service).

FastAPI app with:
  POST /v1/generate   -> run the agent, return generated code + trace
  GET  /health        -> liveness
  WS   /v1/stream     -> stream node-by-node progress (observability)

Run:  uvicorn sdet_agent.interfaces.http_server:app --port 8000
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from typing import Any, Optional


def _load_dotenv() -> None:
    """Best-effort load of a repo-root .env so OPENCODE_API_KEY / model config
    are present even if the server is launched without `set -a; source .env`.

    Existing environment variables always win (we only fill gaps).
    """
    logger = logging.getLogger("sdet_agent.http_server")
    here = os.path.dirname(os.path.abspath(__file__))
    d = here
    for _ in range(6):
        path = os.path.join(d, ".env")
        if os.path.isfile(path):
            try:
                with open(path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, _, val = line.partition("=")
                        key, val = key.strip(), val.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = val
                logger.info("Loaded environment from %s", path)
            except OSError as e:
                logger.warning("Could not read %s: %s", path, e)
            break
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent


_load_dotenv()

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel

from ..core.agent import Agent
from ..core.multiagent import MultiAgentOrchestrator
from ..core.agentic_code_generator import AgenticCodeGenerator
from ..core.tracer import Tracer
from ..core.events import EventEmitter, JsonEmitter
from ..tools import build_registry

logger = logging.getLogger("sdet_agent.http")


def _load_dotenv() -> None:
    """Minimal .env loader (no external dependency).

    Searches upward from this file for a .env file and injects KEY=VALUE pairs
    into os.environ for any key not already set. $HOME is expanded in values so
    paths like PLAYWRIGHT_BROWSERS_PATH=$HOME/... resolve on any machine.
    """
    cur = os.path.dirname(os.path.abspath(__file__))
    path = None
    for _ in range(6):
        cand = os.path.join(cur, ".env")
        if os.path.isfile(cand):
            path = cand
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    if not path:
        return
    home = os.path.expanduser("~")
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if not key or key in os.environ:
                continue
            os.environ[key] = os.path.expanduser(val.replace("$HOME", home))


_load_dotenv()

# Expand $HOME in env vars (e.g. PLAYWRIGHT_BROWSERS_PATH=$HOME/...) since
# .env files don't perform shell expansion.
for _key in ("PLAYWRIGHT_BROWSERS_PATH",):
    _val = os.environ.get(_key, "")
    if "$HOME" in _val:
        os.environ[_key] = _val.replace("$HOME", os.path.expanduser("~"))

app = FastAPI(title="SDET Agent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    url: str
    scenario: str
    session_id: str = ""
    use_qwen: bool = True
    multi_agent: bool = False


class GenerateAgenticRequest(BaseModel):
    """Agent-driven generation: explore the live page via Playwright MCP, then
    generate a deterministic Playwright test from the observations.

    Replaces the recorder-based flow -- no manual action recording required.
    """
    goal: str
    url: str
    repo_dir: str = ""
    starting_url: str = ""
    backend: str = "mcp"
    headless: bool = True
    max_explore_turns: int = 8
    emitter: Any = None  # not part of the HTTP contract; ignored if sent


class ExecuteRequest(BaseModel):
    goal: str
    url: str
    backend: str = "mcp"
    headless: bool = True
    max_turns: int = 30
    assertions: list[dict[str, Any]] = []
    constraints: dict[str, Any] = {}
    # BYOK model override keys (passed through from the user's vault)
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    opencode_api_key: str | None = None
    model_provider: str = "built-in"
    # Optional explicit model id (e.g. "gpt-4o", "gemini-2.5-flash") overriding
    # the provider default. Only used when BYOK is active.
    model: str | None = None


class HealRequest(BaseModel):
    test_path: str
    error_output: str = ""
    url: str = ""
    failing_line: int = 0
    backend: str = "mcp"
    headless: bool = True


class RunSpecRequest(BaseModel):
    test_path: str
    headless: bool = True
    timeout: int = 300


class ChatRequest(BaseModel):
    """Conversational debug turn for a (failed) agentic run."""
    goal: str
    url: str
    backend: str = "playwright"
    last_run: Optional[dict] = None
    message: str
    history: list[dict] = []
    chat_id: Optional[str] = None


ChatRequest.model_rebuild()


class GenerateResponse(BaseModel):
    success: bool
    generated_code: str
    final_node: str
    trace_summary: dict[str, Any]
    error: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "sdet-agent"}


@app.get("/v1/screenshot")
def screenshot() -> Response:
    """Return the current browser viewport as a PNG for live embedding."""
    from ..tools import browser_tools as bt

    try:
        res = bt.browser_screenshot()
    except Exception as e:  # noqa: BLE001 - surface as 404 so the UI shows "idle"
        return Response(status_code=404, media_type="text/plain", content=str(e))
    if not res.get("ok"):
        return Response(status_code=404, media_type="text/plain", content=res.get("error", "no screenshot"))
    import base64

    png = base64.b64decode(res["png"])
    return Response(content=png, media_type="image/png")


@app.get("/v1/agentic/screenshot")
def agentic_screenshot() -> Response:
    """Alias of /v1/screenshot for the workbench LiveBrowser proxy."""
    return screenshot()


@app.post("/v1/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest) -> GenerateResponse:
    tracer = Tracer(enabled=False)
    if req.multi_agent:
        orch = MultiAgentOrchestrator(tracer=tracer)
        r = orch.run(req.url, req.scenario, req.session_id)
        return GenerateResponse(
            success=r["success"],
            generated_code=r["generated_code"],
            final_node=r["final_node"],
            trace_summary=r["trace_summary"],
            error=r.get("error"),
        )
    agent = Agent(tracer=tracer, use_qwen=req.use_qwen)
    res = agent.run(req.url, req.scenario, req.session_id)
    return GenerateResponse(
        success=res.success,
        generated_code=res.generated_code,
        final_node=res.final_node,
        trace_summary=res.trace_summary,
        error=res.error,
    )


@app.post("/v1/generate-agentic")
def generate_agentic(req: GenerateAgenticRequest) -> dict[str, Any]:
    """Explore the live page via Playwright MCP, then generate a Playwright test.

    No manual recording required -- the agent reads the accessibility tree and
    writes correct locators from the start. See ``AgenticCodeGenerator``.
    """
    from ..core.agentic_code_generator import AgenticCodeGenerator

    gen = AgenticCodeGenerator(
        backend=req.backend,
        headless=req.headless,
        max_explore_turns=req.max_explore_turns,
    )
    result = gen.generate(
        goal=req.goal,
        url=req.url,
        repo_dir=req.repo_dir,
        starting_url=req.starting_url or None,
    )
    return result.to_dict()


@app.websocket("/v1/stream")
async def stream(websocket: WebSocket) -> None:
    """Stream the full agent run over WebSocket (OpenCode-style live feed).

    Emits events: node, thinking_delta, content_delta, tool_call,
    tool_result, stdout, stderr, done, error. The agent's model think/content,
    tool invocations, and captured process I/O are all forwarded live.
    """
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        url = data.get("url", "")
        scenario = data.get("scenario", "")
        use_qwen = data.get("use_qwen", True)
        run_id = data.get("session_id", "") or "ws-run"

        emitter = JsonEmitter(send=websocket.send_json, run_id=run_id)
        agent = Agent(tracer=Tracer(enabled=True), use_qwen=use_qwen)
        agent.run_stream(emitter, url, scenario, run_id)
    except Exception as exc:  # noqa: BLE001
        try:
            await websocket.send_json({"event": "error", "message": str(exc)})
        except Exception:  # noqa: BLE001
            pass
    finally:
        await websocket.close()


class _QueueEmitter(EventEmitter):
    """Emits agent events into a queue for NDJSON streaming responses."""

    def __init__(self, q: "queue.Queue") -> None:
        self._q = q

    def emit(self, event_type: str, **data: Any) -> None:
        payload = {"event": event_type, "ts": time.time()}
        payload.update({k: v for k, v in data.items() if v is not None})
        try:
            self._q.put(payload)
        except Exception:  # noqa: BLE001 - never let emit crash the agent
            pass


@app.post("/v1/run-stream")
def run_stream_http(req: GenerateRequest):
    """Stream the full agent run as NDJSON (one JSON object per line).

    Each line is an agent event (node, thinking_delta, content_delta,
    tool_call, tool_result, stdout, stderr, done, error). The workbench API
    proxies these events to the browser WebSocket using its own contract.
    """
    q: "queue.Queue" = queue.Queue()

    def worker() -> None:
        try:
            emitter = _QueueEmitter(q)
            agent = Agent(tracer=Tracer(enabled=True), use_qwen=req.use_qwen)
            agent.run_stream(emitter, req.url, req.scenario, req.session_id)
        except Exception as exc:  # noqa: BLE001
            q.put({"event": "error", "ts": time.time(), "message": str(exc)})
        finally:
            q.put(None)  # sentinel

    def gen():
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        while True:
            item = q.get()
            if item is None:
                break
            yield json.dumps(item, default=str) + "\n"
        t.join(timeout=1.0)

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.get("/v1/tools")
def list_tools() -> dict[str, Any]:
    """Expose the tool registry (same surface as MCP tools/list)."""
    reg = build_registry()
    return {"tools": [t.to_mcp() for t in reg.list_specs()]}


@app.post("/v1/execute")
def execute(req: ExecuteRequest) -> dict[str, Any]:
    """Run a goal-driven agentic test in a live browser (Slack-style)."""
    from ..core.agentic_executor import AgenticExecutor

    ex = AgenticExecutor(
        max_turns=req.max_turns,
        backend=req.backend,
        headless=req.headless,
    )
    res = ex.run(goal=req.goal, url=req.url, assertions=req.assertions, constraints=req.constraints)
    return res.to_dict()


@app.post("/v1/heal")
def heal(req: HealRequest) -> dict[str, Any]:
    """Self-heal a failing deterministic Playwright test via live re-exploration."""
    from ..core.self_healer import SelfHealer

    healer = SelfHealer(backend=req.backend, headless=req.headless)
    res = healer.heal(
        test_path=req.test_path,
        error_output=req.error_output,
        url=req.url,
        failing_line=req.failing_line or None,
    )
    return res.to_dict()


@app.post("/v1/agentic-stream")
def agentic_stream_http(req: ExecuteRequest):
    """Stream a goal-driven agentic run as NDJSON (one JSON object per line).

    Each line is an agent event (node, thinking_delta, tool_call, tool_result,
    done, error). The LLM's reasoning is streamed token-by-token as
    ``thinking_delta`` events so a frontend can show live progress. The workbench
    proxies these events to the browser.
    """
    from ..core.agentic_executor import AgenticExecutor, clear_agentic_stop

    # Clear any stale stop request left over from a previous run so a Stop press
    # for an old run can't cancel the new one.
    clear_agentic_stop()

    q: "queue.Queue" = queue.Queue()

    def worker() -> None:
        try:
            emitter = _QueueEmitter(q)
            byok = None
            if req.model_provider and req.model_provider != "built-in":
                byok = {}
                if req.openai_api_key:
                    byok["openai"] = req.openai_api_key
                if req.anthropic_api_key:
                    byok["anthropic"] = req.anthropic_api_key
                if req.google_api_key:
                    byok["google"] = req.google_api_key
                if req.opencode_api_key:
                    byok["opencode"] = req.opencode_api_key
            ex = AgenticExecutor(
                max_turns=req.max_turns,
                backend=req.backend,
                headless=req.headless,
                emitter=emitter,
                byok=byok,
                model=req.model if byok else None,
            )
            result = ex.run(goal=req.goal, url=req.url, assertions=req.assertions, constraints=req.constraints)
            # Surface a clean "stopped" terminal event when the user hit Stop.
            if getattr(result.trace, "stopped", False):
                q.put({
                    "event": "done",
                    "ts": time.time(),
                    "success": False,
                    "goal_reached": False,
                    "stopped": True,
                    "error": "stopped by user",
                    "trace": result.trace.to_dict(),
                })
        except Exception as exc:  # noqa: BLE001
            q.put({"event": "error", "ts": time.time(), "message": str(exc)})
        finally:
            q.put(None)  # sentinel

    def gen():
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        while True:
            item = q.get()
            if item is None:
                break
            yield json.dumps(item, default=str) + "\n"
        t.join(timeout=1.0)

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/v1/agentic/stop")
def agentic_stop_http() -> dict[str, Any]:
    """Request the currently-running agentic run to stop as soon as possible.

    The worker loop checks the cancel flag after every step, so a long run
    (many LLM calls / heal retries) terminates promptly instead of running to
    completion. The browser session is intentionally left alive so the Live
    Browser keeps showing the page where the run was interrupted.
    """
    from ..core.agentic_executor import request_agentic_stop

    request_agentic_stop()
    return {"ok": True, "stopped": True}


@app.post("/v1/agentic/chat")
def agentic_chat_http(req: ChatRequest):
    """Conversational debug chat for a (failed) agentic run.

    The conversation is persisted under a UUID ``chat_id`` so the LLM keeps
    memory of every turn in the window across reloads. Streams ``chat_delta``
    events (the model's live output) and a final ``chat`` event carrying the
    parsed ``{chat_id, reply, revised_goal, actions}``.
    """
    q: "queue.Queue" = queue.Queue()

    def worker() -> None:
        try:
            emitter = _QueueEmitter(q)
            from ..core import agentic_chat, chat_store

            # Resolve / create the persisted chat session.
            if req.chat_id:
                chat_id = chat_store.ensure_chat(
                    req.chat_id, req.goal, req.url, req.backend
                )
            else:
                chat_id = chat_store.create_chat(req.goal, req.url, req.backend)

            # Persist the user's message and load the full conversation so far.
            chat_store.append_message(chat_id, "user", req.message)
            history = chat_store.get_history(chat_id)
            # The current message is sent separately below; exclude it from the
            # history we hand to the model to avoid duplication.
            prior_history = history[:-1] if history else []

            result = agentic_chat.run_chat(
                goal=req.goal,
                url=req.url,
                last_run=req.last_run,
                message=req.message,
                history=prior_history,
                backend=req.backend,
                emitter=emitter,
            )

            # Persist the assistant reply for future memory.
            chat_store.append_message(
                chat_id, "assistant", result.get("reply") or ""
            )
            emitter.emit(
                "chat",
                chat_id=chat_id,
                reply=result.get("reply"),
                revised_goal=result.get("revised_goal"),
                actions=result.get("actions"),
            )
        except Exception as exc:  # noqa: BLE001
            q.put({"event": "error", "ts": time.time(), "message": str(exc)})
        finally:
            q.put(None)  # sentinel

    def gen():
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        while True:
            item = q.get()
            if item is None:
                break
            yield json.dumps(item, default=str) + "\n"
        t.join(timeout=1.0)

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.get("/v1/agentic/chat/{chat_id}")
def agentic_chat_history_http(chat_id: str):
    """Return a persisted chat session and its full message history."""
    from ..core import chat_store

    chat = chat_store.get_chat(chat_id)
    if not chat:
        return JSONResponse(
            status_code=404, content={"error": "chat not found"}
        )
    return {
        "chat_id": chat_id,
        "goal": chat.get("goal"),
        "url": chat.get("url"),
        "backend": chat.get("backend"),
        "messages": chat_store.get_history(chat_id),
    }


@app.post("/v1/run-spec")
def run_spec_endpoint(req: RunSpecRequest) -> dict[str, Any]:
    """Execute a generated Playwright spec for real via @playwright/test.

    Unlike /v1/execute (goal-driven LLM planner), this actually RUNS the spec
    file, so locator/assertion failures surface as real Playwright errors that
    the self-heal loop can consume.
    """
    from ..core.spec_runner import run_spec

    return run_spec(test_path=req.test_path, headless=req.headless, timeout=req.timeout)

