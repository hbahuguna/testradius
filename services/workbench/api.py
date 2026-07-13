from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Dict, List, Optional, Set

import logging
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from testsquad_workbench.sdet_procedure.inference.session_manager import SessionManager
from testsquad_workbench.sdet_procedure.inference.conversation_state import ConversationState
from testsquad_workbench.main import proxy_router
from testsquad_workbench.ticket_service import JiraClient, set_config, get_client, clear_config

logger = logging.getLogger(__name__)


MODEL_PATH = os.environ.get("SDET_MODEL_PATH")
BASE_MODEL = os.environ.get("SDET_BASE_MODEL", "Qwen/Qwen3-8B")
SESSION_CONTEXT_API = os.environ.get("SESSION_CONTEXT_API", "http://localhost:9800")
OPENCODE_SESSION_ID = os.environ.get("OPENCODE_SESSION_ID", "").strip()
# Standalone SDET-agent service (apps/sdet-agent) that generates the test code
# and streams OpenCode-style events. The workbench proxies those events to the
# browser over the existing WebSocket using the "opencode_*" message contract.
SDET_AGENT_API = os.environ.get("SDET_AGENT_API", "http://localhost:8006")
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


def _build_sdet_prompt(state: ConversationState, for_opencode: bool = False) -> str:
    """Build a prompt for the SDET model from the full session context (N0-N13 data).

    `for_opencode` adds repo-aware instructions because OpenCode runs with the
    automation repo as its working directory and can read/reuse existing files
    itself (no file contents are embedded in this prompt).
    """
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
    lines.append("STRICT ADHERENCE RULES:")
    lines.append("- Implement ONLY what the user's instructions and any attached Jira ticket or context explicitly describe. Do NOT assume, infer, or invent fields, input types, actions, or behaviors that are not specified.")
    lines.append("- Use the literal meaning of each instruction. Example: 'Link to Resume' is a URL/text link field, NOT a file upload control. Only use file uploads (setInputFiles) when the instructions explicitly say to attach, browse, or upload a file.")
    lines.append("- When a step is ambiguous, follow the literal text rather than guessing intent.")

    if for_opencode:
        lines.append("")
        lines.append("REPO ACCESS (no file contents are supplied in this prompt - discover them yourself):")
        lines.append("- The automation repo is mounted at your working directory. Do NOT expect page-object or utility source to be pasted into the prompt.")
        lines.append("- Use your tools (Glob/Grep/Read) to locate existing page objects (e.g. '**/pages/*.ts', '**/page-objects/**') and utilities/helpers, then IMPORT and REUSE them instead of duplicating locators or logic. Follow the repo's existing test patterns and file layout.")
        lines.append("- Write the generated test to the repo's tests directory (e.g. 'tests/', 'e2e/', 'specs/') using its naming conventions.")

    lines.append("")
    lines.append("Output ONLY valid TypeScript code inside a single code block. No explanation.")

    return "\n".join(lines)


def _build_sdet_scenario(state: ConversationState) -> str:
    """Concise scenario handed to the sdet-agent.

    The agent has its own per-node instructions, so we pass only the concrete
    test facts (URL, feature, type, jira context, recorded actions, elements).

    Priority model (requested by the user):
      - Jira ticket is the PRIMARY source when present.
      - Recorded actions are supplementary; include only steps that do NOT
        conflict with the Jira ticket. On any conflict, Jira wins.
      - If neither is present, fall back to the free-text scenario.
    """
    lines: list[str] = []

    has_jira = bool(getattr(state, "jira_context", ""))
    has_actions = bool(state.recorded_actions)
    has_elements = bool(state.selected_elements)

    if has_jira:
        lines.append("JIRA CONTEXT (HIGHEST PRIORITY — drive the test from this):")
        lines.append(state.jira_context.strip())
        lines.append("")

    if has_actions:
        lines.append(
            "RECORDED ACTIONS (supplementary — include only steps that do NOT "
            "conflict with the Jira ticket above; Jira wins on any conflict):"
        )
        for a in state.recorded_actions:
            loc = a.locator or ""
            label = a.label or (a.text or "")[:40] or a.tag
            val = a.value or ""
            lines.append(f'  {a.step_order}. {a.action_type} on "{label}"  -> {loc}  value="{val}"')
        lines.append("")

    if has_elements:
        lines.append("SELECTED ELEMENTS (N9):")
        for i, el in enumerate(state.selected_elements, 1):
            tag = el.get("tag", "?")
            text = el.get("text", "") or el.get("label", "") or ""
            css = el.get("css_path", el.get("cssPath", ""))
            role = el.get("role", "")
            aria = el.get("aria_label", "")
            lines.append(f'  {i}. <{tag}> text="{text}" css="{css}" role="{role}" aria="{aria}"')
        lines.append("")

    if not has_jira and not has_actions:
        lines.append(f"Scenario: {state.scenario_description or 'User flow test'}")
        lines.append("")

    lines.append(f"URL: {state.url}")
    lines.append(f"Feature: {state.feature_type or 'form'}")
    lines.append(f"Test Type: {state.test_type or 'positive'}")

    # Explicit priority rule so the model cannot default back to "merge blindly".
    if has_jira and has_actions:
        lines.append(
            "PRIORITY RULE: The Jira ticket is authoritative. Produce the UNION of "
            "Jira + recorded actions; where a step conflicts, use the Jira version."
        )
    elif has_jira:
        lines.append("PRIORITY RULE: Generate the test strictly from the Jira ticket above.")
    elif has_actions:
        lines.append("PRIORITY RULE: Generate the test from the recorded actions above.")

    lines.append("")
    lines.append("Generate a Playwright test in TypeScript using accessible locators.")
    lines.append("- Prefer getByRole / getByLabel / getByPlaceholder / getByText; use realistic test data.")
    lines.append("- Include beforeEach, auto-waiting assertions (URL / visibility / value checks), and no fixed timeouts.")
    lines.append("- Treat 'Link to Resume' as a URL/text field, NOT a file upload control.")
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


# sdet-agent event names (mirror sdet_agent.core.events constants without
# importing the package into this process).
_SDET_EV_NODE = "node"
_SDET_EV_THINKING = "thinking_delta"
_SDET_EV_CONTENT = "content_delta"
_SDET_EV_TOOL_CALL = "tool_call"
_SDET_EV_TOOL_RESULT = "tool_result"
_SDET_EV_STDOUT = "stdout"
_SDET_EV_STDERR = "stderr"
_SDET_EV_DONE = "done"
_SDET_EV_ERROR = "error"


async def _stream_sdet_events(session_id: str, session, fallback_code: str = "") -> None:
    """Stream SDET-agent events through the WebSocket once the session reaches N14.

    The standalone sdet-agent service runs the full 16-node procedure graph and
    streams OpenCode-style events as NDJSON. We proxy each event to the browser
    using the existing "opencode_*" WebSocket contract the frontend already
    renders, so the UI needs no changes.
    """
    ws = session.ws_connections
    if not ws:
        return

    state = session.state

    await _send_ws_json(ws, {
        "type": "opencode_event", "event": "system",
        "content": (
            f"Analyzing session context: {len(state.recorded_actions)} recorded actions, "
            f"{len(state.selected_elements)} selected elements, "
            f"feature={state.feature_type or '?'}, type={state.test_type or '?'}"
        ),
    })

    await _send_ws_json(ws, {
        "type": "opencode_event", "event": "system",
        "content": "Running SDET agent (N0-N14) with full session context...",
    })

    scenario = _build_sdet_scenario(state)
    final_code = ""
    error_message: Optional[str] = None

    try:
        async with httpx.AsyncClient(timeout=300.0) as c:
            async with c.stream(
                "POST",
                f"{SDET_AGENT_API}/v1/run-stream",
                json={
                    "url": state.url,
                    "scenario": scenario,
                    "session_id": session_id,
                    "use_qwen": True,
                },
            ) as resp:
                if resp.status_code != 200:
                    body = ""
                    try:
                        body = (await resp.aread()).decode()[:300]
                    except Exception:
                        pass
                    error_message = f"SDET agent returned HTTP {resp.status_code}: {body}"
                else:
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            evt = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        etype = evt.get("event")

                        if etype == _SDET_EV_DONE:
                            code = evt.get("generated_code", "") or ""
                            if code:
                                final_code = code
                                await _send_ws_json(ws, {
                                    "type": "opencode_code_chunk",
                                    "content": code,
                                    "accumulated": code,
                                })
                            continue

                        if etype == _SDET_EV_ERROR:
                            error_message = evt.get("message", "SDET agent error")
                            await _send_ws_json(ws, {
                                "type": "opencode_error",
                                "content": error_message,
                            })
                            continue

                        for msg in _map_sdet_event(evt, etype):
                            await _send_ws_json(ws, msg)
    except httpx.RequestError as e:
        error_message = f"SDET agent request failed: {e}"

    if not final_code:
        if error_message:
            await _send_ws_json(ws, {
                "type": "opencode_error",
                "content": f"{error_message} Falling back to local template.",
            })
        final_code = fallback_code

    if final_code:
        await _push_session_context("/api/session/test-code", {
            "session_id": session_id,
            "code": final_code,
            "language": "typescript",
            "description": "SDET-agent generated test from workbench session",
        })
        await _send_ws_json(ws, {
            "type": "opencode_complete",
            "test_code": final_code,
            "is_complete": True,
        })

    await _send_ws_json(ws, {
        "type": "opencode_event", "event": "tool_use",
        "tool": "write",
        "path": "tests/e2e/test_session.ts",
        "file_content": final_code,
        "status": "completed",
    })


def _humanize_node(name: str) -> str:
    """Turn a graph node name like 'ParseRequirement' into 'Parse Requirement'."""
    out = re.sub(r"(?<!^)(?=[A-Z])", " ", name or "").strip()
    return out or name


def _map_sdet_event(evt: Dict[str, Any], etype: str) -> List[Dict[str, Any]]:
    """Translate a single sdet-agent event into workbench WS message(s)."""
    if etype == _SDET_EV_NODE:
        op_name = _humanize_node(evt.get("name") or evt.get("node_id", ""))
        return [{
            "type": "opencode_event", "event": "node",
            "content": f"▶ {op_name}",
        }]
    if etype == _SDET_EV_THINKING:
        text = evt.get("text", "")
        if not text:
            return []
        return [{"type": "opencode_event", "event": "thinking", "content": text}]
    if etype == _SDET_EV_CONTENT:
        text = evt.get("text", "")
        if not text:
            return []
        return [{"type": "opencode_event", "event": "text", "content": text}]
    if etype == _SDET_EV_TOOL_CALL:
        args = evt.get("arguments", {}) or {}
        cmd = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
        return [{
            "type": "opencode_event", "event": "tool_use",
            "tool": evt.get("name", ""),
            "status": "running",
            "command": cmd[:600],
        }]
    if etype == _SDET_EV_TOOL_RESULT:
        result = evt.get("result") or evt.get("error") or ""
        if not isinstance(result, str):
            result = json.dumps(result, default=str)
        return [{
            "type": "opencode_event", "event": "tool_use",
            "tool": evt.get("name", ""),
            "status": "completed",
            "output": result[:600],
        }]
    if etype in (_SDET_EV_STDOUT, _SDET_EV_STDERR):
        line = evt.get("line", "")
        if not line:
            return []
        return [{"type": "opencode_event", "event": "text", "content": line}]
    return []


class ScrapeRequest(BaseModel):
    url: str
    timeout_ms: int = 30000


class AgenticExecuteRequest(BaseModel):
    """Proxied to the standalone SDET-agent service (apps/sdet-agent) /v1/execute.

    Mirrors the agentic executor contract so the workbench can run goal-driven,
    live-browser agentic tests without re-implementing the planner/loop.
    """
    goal: str
    url: str
    backend: str = "mcp"
    headless: bool = True
    max_turns: int = 30
    assertions: List[Dict[str, Any]] = []
    constraints: Dict[str, Any] = {}


class AgenticHealRequest(BaseModel):
    """Proxied to apps/sdet-agent /v1/heal (self-healing for failing tests)."""
    test_path: str
    error_output: str = ""
    url: str = ""
    failing_line: int = 0
    backend: str = "mcp"
    headless: bool = True


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


class JiraConnectRequest(BaseModel):
    session_id: str
    instance_url: str
    email: str
    api_token: str


class JiraSearchRequest(BaseModel):
    session_id: str
    query: str = ""
    jql: str = ""
    max_results: int = 10


class JiraIssueRequest(BaseModel):
    session_id: str
    issue_key: str


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


@app.post("/api/workbench/agentic/execute")
async def agentic_execute(req: AgenticExecuteRequest):
    """Run a goal-driven agentic test via the standalone SDET-agent service.

    The workbench delegates to apps/sdet-agent's /v1/execute, which owns the
    observe->plan->act loop, locator resolution, and assertion verification.
    """
    try:
        async with httpx.AsyncClient(timeout=600.0) as c:
            resp = await c.post(
                f"{SDET_AGENT_API}/v1/execute",
                json=req.model_dump(),
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=(resp.text or "")[:400],
                )
            return resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"SDET agent unreachable: {e}")


@app.post("/api/workbench/agentic/heal")
async def agentic_heal(req: AgenticHealRequest):
    """Self-heal a failing Playwright test via the standalone SDET-agent service."""
    try:
        async with httpx.AsyncClient(timeout=600.0) as c:
            resp = await c.post(
                f"{SDET_AGENT_API}/v1/heal",
                json=req.model_dump(),
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=(resp.text or "")[:400],
                )
            return resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"SDET agent unreachable: {e}")


def _abs_test_path(repo_dir: Optional[str], test_path: Optional[str]) -> Optional[str]:
    if not test_path:
        return test_path
    if os.path.isabs(test_path):
        return test_path
    return os.path.abspath(os.path.join(repo_dir or ".", test_path))


def _write_test_file(repo_dir: Optional[str], test_path: Optional[str], code: str) -> None:
    if not test_path:
        return
    p = _abs_test_path(repo_dir, test_path)
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w") as f:
            f.write(code)
    except Exception as e:  # pragma: no cover - best effort artifact write
        logger.warning("Failed to write test file %s: %s", p, e)


class AgenticGenerateRunRequest(BaseModel):
    """One-click: generate a Playwright spec, execute it (goal-based), then heal on failure.

    Chains the standalone SDET-agent's /v1/generate -> /v1/execute -> /v1/heal and
    repeats the execute->heal cycle up to `max_attempts` until the test passes.
    """
    scenario: str
    url: str
    goal: str
    assertions: List[Dict[str, Any]] = []
    repo_dir: Optional[str] = None
    test_path: Optional[str] = None
    # Already-generated spec (e.g. from the N0-N14 opencode session). When
    # provided we persist it as the real spec file and skip the LLM generator,
    # which can be slow/flaky. Falls back to /v1/generate otherwise.
    generated_code: Optional[str] = None
    backend: str = "mcp"
    headless: bool = True
    max_turns: int = 30
    max_attempts: int = 5


class AgenticGenerateAgenticRequest(BaseModel):
    """Recorder-free generation: explore the live page via Playwright MCP, then
    generate a deterministic Playwright test, then run + self-heal.

    Chains the standalone SDET-agent's /v1/generate-agentic -> /v1/run-spec ->
    /v1/heal and repeats the run->heal cycle up to `max_attempts`. No manual
    action recording is required -- the agent reads the accessibility tree.
    """
    goal: str
    url: str
    repo_dir: Optional[str] = None
    test_path: Optional[str] = None
    starting_url: Optional[str] = None
    backend: str = "mcp"
    headless: bool = True
    max_explore_turns: int = 8
    max_attempts: int = 5


def _derive_assertions(code: str) -> List[Dict[str, Any]]:
    """Best-effort extraction of executor assertions from a generated Playwright spec.

    Produces visibility/url assertions compatible with the agentic executor so the
    generated test is actually verified (never vacuously passed). Locators are
    formatted as the executor expects: 'role|name' / 'label|name' / 'text|name'.
    """
    if not code:
        return []
    out: List[Dict[str, Any]] = []
    seen = set()

    def add(d: Dict[str, Any]) -> None:
        key = (d.get("type"), d.get("target"), d.get("expected", d.get("pattern")))
        if key in seen:
            return
        seen.add(key)
        out.append(d)

    # getByRole('X', { name: /Y/i }) or name: "Y"
    for m in re.finditer(
        r"getByRole\(\s*['\"]([^'\"]+)['\"]\s*,\s*\{\s*name:\s*(?:/([^/]+)/i?|['\"]([^'\"]+)['\"])",
        code,
    ):
        role, name = m.group(1), m.group(2) or m.group(3)
        add({"type": "visibility", "target": f"{role}|{name}", "kind": "role",
             "description": f"visible {role} {name}"})
    for sel, kind in (("getByLabel", "label"), ("getByPlaceholder", "placeholder"), ("getByText", "text")):
        for m in re.finditer(rf"{sel}\(\s*(?:/([^/]+)/i?|['\"]([^'\"]+)['\"])", code):
            name = m.group(1) or m.group(2)
            add({"type": "visibility", "target": f"{kind}|{name}", "kind": kind,
                 "description": f"visible {kind} {name}"})
    for m in re.finditer(r"toHaveURL\(\s*(?:/([^/]+)/i?|['\"]([^'\"]+)['\"])", code):
        pat = m.group(1) or m.group(2)
        add({"type": "url", "target": "", "pattern": pat, "description": f"url matches {pat}"})
    return out


def _fallback_assertions(goal: str) -> List[Dict[str, Any]]:
    """When no assertions can be derived, build a minimal visibility assertion
    from common CTA keywords in the goal so the run is never vacuous."""
    g = (goal or "").lower()
    if "submit" in g:
        return [{"type": "visibility", "target": "text|Submit", "kind": "text",
                 "description": "submit control visible"}]
    if "apply" in g:
        return [{"type": "visibility", "target": "text|Apply", "kind": "text",
                 "description": "apply control visible"}]
    return []


async def _call_execute(
    req: AgenticGenerateRunRequest,
    assertions: List[Dict[str, Any]],
    goal_override: Optional[str] = None,
) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=600.0) as c:
        ex = await c.post(
            f"{SDET_AGENT_API}/v1/execute",
            json={
                "goal": goal_override or req.goal,
                "url": req.url,
                "backend": req.backend,
                "headless": req.headless,
                "max_turns": req.max_turns,
                "assertions": assertions,
            },
        )
        return ex.json() if ex.status_code == 200 else {
            "success": False, "error": (ex.text or "")[:300],
        }


async def _call_run_spec(req: AgenticGenerateRunRequest) -> Dict[str, Any]:
    """Execute the generated spec for real via @playwright/test (SDET agent /
    v1/run-spec). Returns {success, error_output, returncode}."""
    async with httpx.AsyncClient(timeout=600.0) as c:
        ex = await c.post(
            f"{SDET_AGENT_API}/v1/run-spec",
            json={
                "test_path": _abs_test_path(req.repo_dir, req.test_path),
                "headless": req.headless,
                "timeout": 300,
            },
        )
        return ex.json() if ex.status_code == 200 else {
            "success": False, "error": (ex.text or "")[:300],
        }


async def _call_heal(req: AgenticGenerateRunRequest, error_output: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=600.0) as c:
        hl = await c.post(
            f"{SDET_AGENT_API}/v1/heal",
            json={
                "test_path": _abs_test_path(req.repo_dir, req.test_path),
                "error_output": error_output,
                "url": req.url,
                "backend": req.backend,
                "headless": req.headless,
            },
        )
        return hl.json() if hl.status_code == 200 else {
            "success": False, "error": (hl.text or "")[:300],
        }


async def _call_generate(req: AgenticGenerateRunRequest) -> Dict[str, Any]:
    """Generate a Playwright spec via the SDET agent. Returns {code, error}."""
    async with httpx.AsyncClient(timeout=600.0) as c:
        gen = await c.post(
            f"{SDET_AGENT_API}/v1/generate",
            json={"url": req.url, "scenario": req.scenario, "use_qwen": False},
        )
        if gen.status_code != 200:
            return {"code": None, "error": (gen.text or "")[:300]}
        gd = gen.json()
        return {"code": gd.get("generated_code"), "error": gd.get("error")}


@app.post("/api/workbench/agentic/generate-run")
async def agentic_generate_run(req: AgenticGenerateRunRequest):
    """Generate a spec, then run a self-healing agentic loop until the test passes.

    Loop (up to `max_attempts`):
      1. derive assertions from the current spec (or the goal as fallback),
      2. execute the goal-based agentic run,
      3. if it reached the goal -> done,
      4. otherwise heal the spec using the Playwright error + N0-N14/generation
         context, rewrite the spec, and repeat.
    """
    out: Dict[str, Any] = {
        "generated_code": None,
        "generate_error": None,
        "attempts": [],
        "execute": None,
        "heal": None,
        "success": False,
    }

    # 1) Obtain the spec. Prefer a spec already generated upstream (e.g. the
    # N0-N14 opencode session produced working code) -- persist it as the
    # real spec file and skip the LLM generator entirely. Otherwise call
    # /v1/generate as a fallback.
    if req.generated_code and req.test_path:
        out["generated_code"] = req.generated_code
        _write_test_file(req.repo_dir, req.test_path, out["generated_code"])
    else:
        try:
            gen = await _call_generate(req)
            out["generated_code"] = gen["code"]
            out["generate_error"] = gen["error"]
            if req.test_path and out["generated_code"]:
                _write_test_file(req.repo_dir, req.test_path, out["generated_code"])
        except httpx.HTTPError as e:
            out["generate_error"] = f"SDET agent unreachable (generate): {e}"

    attempts: List[Dict[str, Any]] = []
    last_execute: Dict[str, Any] | None = None
    last_heal: Dict[str, Any] | None = None
    success = False
    loop_ctx = ""

    for attempt in range(1, max(1, req.max_attempts) + 1):
        # Ensure we always have a spec file to execute/heal against. If the
        # initial generate produced nothing (or the file wasn't persisted),
        # regenerate here so the self-heal loop can still run.
        test_file = _abs_test_path(req.repo_dir, req.test_path)
        if (not test_file or not os.path.exists(test_file)) and not out["generated_code"]:
            try:
                gen = await _call_generate(req)
                out["generated_code"] = gen["code"]
                if not out["generate_error"]:
                    out["generate_error"] = gen["error"]
            except httpx.HTTPError as e:
                out["generate_error"] = f"SDET agent unreachable (generate): {e}"
            if req.test_path and out["generated_code"]:
                _write_test_file(req.repo_dir, req.test_path, out["generated_code"])

        # Feed every prior attempt's error back into the healer's context so the
        # next healing pass carries the full history and avoids repeating mistakes.
        attempt_ctx = ""
        if attempt > 1 and loop_ctx:
            attempt_ctx = (
                f"\n\nCONTEXT FROM PREVIOUS ATTEMPTS (these locators/flows already "
                f"failed -- do not repeat them):\n{loop_ctx}"
            )

        # Execute the GENERATED SPEC for real via @playwright/test. This is the
        # key fix: the spec file is actually run, so locator/assertion failures
        # surface as real Playwright errors rather than being silently skipped.
        try:
            ex = await _call_run_spec(req)
        except httpx.HTTPError as e:
            ex = {"success": False, "error": f"SDET agent unreachable (run-spec): {e}"}
        last_execute = ex

        entry: Dict[str, Any] = {"attempt": attempt, "execute": ex, "heal": None}
        attempts.append(entry)

        if ex.get("success"):
            logger.info("agentic attempt %d: spec PASSED", attempt)
            success = True
            break
        logger.warning(
            "agentic attempt %d: spec FAILED -> %s",
            attempt,
            (ex.get("error_output") or ex.get("error") or "")[:600],
        )

        # Heal: feed the real Playwright error + full N0-N14/generation context
        # so the healer can re-evaluate and fix the broken locators in the spec.
        err = (ex.get("error_output") or ex.get("error") or "")

        # The healer reads the spec from disk; make sure it exists. If we have no
        # spec at all (generation failed), we cannot self-heal this attempt -- but
        # we keep looping (up to max_attempts) so a later attempt can regenerate
        # or the upstream-provided spec can be re-persisted. Record a clear error.
        test_file = _abs_test_path(req.repo_dir, req.test_path)
        if (not test_file or not os.path.exists(test_file)) and out["generated_code"]:
            _write_test_file(req.repo_dir, req.test_path, out["generated_code"])
        if not test_file or not os.path.exists(test_file):
            hl: Dict[str, Any] = {
                "success": False,
                "error": "no generated spec available to heal (generation produced no code)",
            }
            last_heal = hl
            entry["heal"] = hl
            out["heal"] = hl
            continue

        ctx = (
            f"Original scenario / N0-N14 context:\n{req.scenario}\n\n"
            f"Generated test:\n{out['generated_code'] or ''}\n\n"
            f"Previous run error:\n{err}{attempt_ctx}"
        )
        try:
            hl = await _call_heal(req, ctx)
        except httpx.HTTPError as e:
            hl = {"success": False, "error": f"SDET agent unreachable (heal): {e}"}
        last_heal = hl
        entry["heal"] = hl

        if hl.get("success"):
            logger.info("agentic attempt %d: heal produced corrected code", attempt)
        else:
            logger.warning(
                "agentic attempt %d: heal FAILED -> %s",
                attempt,
                (hl.get("error") or "")[:600],
            )

        if hl.get("healed_code"):
            out["generated_code"] = hl["healed_code"]
            if req.test_path:
                _write_test_file(req.repo_dir, req.test_path, hl["healed_code"])

        # Accumulate context for the next execute attempt.
        changed = ", ".join(hl.get("changed_locators") or []) if hl else ""
        loop_ctx += (
            f"\n[attempt {attempt}] FAILED: {err}\n"
            f"[attempt {attempt}] healed locators: {changed or 'none'}\n"
        )

    out["attempts"] = attempts
    out["execute"] = last_execute
    out["heal"] = last_heal
    out["success"] = success
    return out


async def _call_generate_agentic(req: AgenticGenerateAgenticRequest) -> Dict[str, Any]:
    """Explore the live page via Playwright MCP and generate a spec.

    Returns {success, generated_code, error, observations, exploration_log}.
    """
    async with httpx.AsyncClient(timeout=600.0) as c:
        gen = await c.post(
            f"{SDET_AGENT_API}/v1/generate-agentic",
            json={
                "goal": req.goal,
                "url": req.url,
                "repo_dir": req.repo_dir or "",
                "starting_url": req.starting_url or "",
                "backend": req.backend,
                "headless": req.headless,
                "max_explore_turns": req.max_explore_turns,
            },
        )
        if gen.status_code != 200:
            return {"success": False, "generated_code": None,
                    "error": (gen.text or "")[:300], "observations": [],
                    "exploration_log": []}
        gd = gen.json()
        return {
            "success": bool(gd.get("success")),
            "generated_code": gd.get("generated_code"),
            "error": gd.get("error"),
            "observations": gd.get("observations", []),
            "exploration_log": gd.get("exploration_log", []),
        }


@app.post("/api/workbench/agentic/generate-agentic")
async def agentic_generate_agentic(req: AgenticGenerateAgenticRequest):
    """Recorder-free: explore via MCP, generate a spec, run + self-heal.

    Loop (up to `max_attempts`):
      1. /v1/generate-agentic explores the live page and returns Playwright code
         with correct accessible locators,
      2. persist the spec and run it for real via /v1/run-spec,
      3. if it failed, /v1/heal rewrites the broken locators, then repeat.
    """
    out: Dict[str, Any] = {
        "generated_code": None,
        "generate_error": None,
        "observations": [],
        "exploration_log": [],
        "attempts": [],
        "execute": None,
        "heal": None,
        "success": False,
    }

    # 1) Explore + generate.
    try:
        gen = await _call_generate_agentic(req)
    except httpx.HTTPError as e:
        gen = {"success": False, "generated_code": None,
               "error": f"SDET agent unreachable (generate-agentic): {e}",
               "observations": [], "exploration_log": []}
    out["generated_code"] = gen.get("generated_code")
    out["generate_error"] = gen.get("error")
    out["observations"] = gen.get("observations", [])
    out["exploration_log"] = gen.get("exploration_log", [])
    if not out["generated_code"]:
        out["success"] = False
        return out
    if req.test_path:
        _write_test_file(req.repo_dir, req.test_path, out["generated_code"])

    # 2) Run + heal loop (reuses the same helper as generate-run).
    attempts: List[Dict[str, Any]] = []
    last_execute: Dict[str, Any] | None = None
    last_heal: Dict[str, Any] | None = None
    success = False
    loop_ctx = ""

    for attempt in range(1, max(1, req.max_attempts) + 1):
        test_file = _abs_test_path(req.repo_dir, req.test_path)
        if (not test_file or not os.path.exists(test_file)) and out["generated_code"]:
            _write_test_file(req.repo_dir, req.test_path, out["generated_code"])

        attempt_ctx = ""
        if attempt > 1 and loop_ctx:
            attempt_ctx = (
                f"\n\nCONTEXT FROM PREVIOUS ATTEMPTS (these locators/flows already "
                f"failed -- do not repeat them):\n{loop_ctx}"
            )

        try:
            ex = await _call_run_spec(req)
        except httpx.HTTPError as e:
            ex = {"success": False, "error": f"SDET agent unreachable (run-spec): {e}"}
        last_execute = ex
        entry: Dict[str, Any] = {"attempt": attempt, "execute": ex, "heal": None}
        attempts.append(entry)

        if ex.get("success"):
            logger.info("generate-agentic attempt %d: spec PASSED", attempt)
            success = True
            break
        logger.warning(
            "generate-agentic attempt %d: spec FAILED -> %s",
            attempt,
            (ex.get("error_output") or ex.get("error") or "")[:600],
        )

        err = (ex.get("error_output") or ex.get("error") or "")
        test_file = _abs_test_path(req.repo_dir, req.test_path)
        if (not test_file or not os.path.exists(test_file)) and out["generated_code"]:
            _write_test_file(req.repo_dir, req.test_path, out["generated_code"])
        if not test_file or not os.path.exists(test_file):
            hl = {"success": False,
                  "error": "no generated spec available to heal (generation produced no code)"}
            last_heal = hl
            entry["heal"] = hl
            out["heal"] = hl
            continue

        ctx = (
            f"Goal / scenario:\n{req.goal}\n\n"
            f"Generated test:\n{out['generated_code'] or ''}\n\n"
            f"Previous run error:\n{err}{attempt_ctx}"
        )
        try:
            hl = await _call_heal(req, ctx)
        except httpx.HTTPError as e:
            hl = {"success": False, "error": f"SDET agent unreachable (heal): {e}"}
        last_heal = hl
        entry["heal"] = hl

        if hl.get("success"):
            logger.info("generate-agentic attempt %d: heal produced corrected code", attempt)
        if hl.get("healed_code"):
            out["generated_code"] = hl["healed_code"]
            if req.test_path:
                _write_test_file(req.repo_dir, req.test_path, hl["healed_code"])

        changed = ", ".join(hl.get("changed_locators") or []) if hl else ""
        loop_ctx += (
            f"\n[attempt {attempt}] FAILED: {err}\n"
            f"[attempt {attempt}] healed locators: {changed or 'none'}\n"
        )

    out["attempts"] = attempts
    out["execute"] = last_execute
    out["heal"] = last_heal
    out["success"] = success
    return out


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
        "automation_repo": req.automation_repo or "",
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
                _stream_sdet_events(
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
                        _stream_sdet_events(
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


@app.post("/api/workbench/ticket/jira/connect")
async def jira_connect(req: JiraConnectRequest):
    try:
        client = JiraClient(req.instance_url, req.email, req.api_token)
        ok = await client.verify()
        if not ok:
            raise HTTPException(status_code=401, detail="Could not verify Jira credentials")
        set_config(req.session_id, req.instance_url, req.email, req.api_token)
        return {"status": "connected", "display_name": ""}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/workbench/ticket/jira/search")
async def jira_search(req: JiraSearchRequest):
    client = get_client(req.session_id)
    if not client:
        raise HTTPException(status_code=401, detail="Jira not configured for this session")
    jql = req.jql or f'summary ~ "{req.query}" OR description ~ "{req.query}" ORDER BY updated DESC'
    try:
        results = await client.search(jql, req.max_results)
        return {"issues": results}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Jira search failed: {e}")


@app.post("/api/workbench/ticket/jira/issue")
async def jira_issue(req: JiraIssueRequest):
    client = get_client(req.session_id)
    if not client:
        raise HTTPException(status_code=401, detail="Jira not configured for this session")
    try:
        issue = await client.get_issue(req.issue_key)
        return {"issue": issue}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch issue: {e}")


@app.post("/api/workbench/ticket/jira/disconnect")
async def jira_disconnect(req: JiraIssueRequest):
    clear_config(req.session_id)
    return {"status": "disconnected"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
