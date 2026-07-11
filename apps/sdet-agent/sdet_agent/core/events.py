"""Event streaming protocol (OpenCode-style live UI feed).

The SDET agent emits a stream of structured events so a frontend can render
the run like OpenCode does:

  thinking_delta  - incremental "think" text (model reasoning)
  content_delta   - incremental assistant "content" text (model answer)
  tool_call       - an agent tool invocation (name + arguments)
  tool_result     - the result of a tool invocation
  node            - graph node entered (progress marker)
  stdout          - captured process stdout line
  stderr          - captured process stderr line
  done            - run finished (success + generated code)
  error           - run failed

An EventEmitter is the sink. The HTTP/WebSocket server adapts it to a socket;
the CLI adapts it to the terminal; tests use a collecting emitter.
"""

from __future__ import annotations

import contextvars
import logging
import time
from typing import Any, Callable, Optional

# --- event type names -------------------------------------------------------
EV_THINKING = "thinking_delta"
EV_CONTENT = "content_delta"
EV_TOOL_CALL = "tool_call"
EV_TOOL_RESULT = "tool_result"
EV_NODE = "node"
EV_STDOUT = "stdout"
EV_STDERR = "stderr"
EV_DONE = "done"
EV_ERROR = "error"

# Context-local emitter so tools and logging can emit without threading the
# sink through every call site.
_current_emitter: contextvars.ContextVar["EventEmitter"] = contextvars.ContextVar(
    "sdet_event_emitter", default=None
)


class EventEmitter:
    """Sink for agent events. Override `emit` (and optionally `close`)."""

    def emit(self, event_type: str, **data: Any) -> None:  # noqa: D401
        raise NotImplementedError

    def close(self) -> None:
        pass


class JsonEmitter(EventEmitter):
    """Emits pre-serialized JSON dicts via a `send` callable (e.g. websocket)."""

    def __init__(self, send: Callable[[dict], Any], run_id: str = "") -> None:
        self._send = send
        self._run_id = run_id

    def emit(self, event_type: str, **data: Any) -> None:
        payload = {"event": event_type, "ts": time.time(), "run_id": self._run_id}
        payload.update({k: v for k, v in data.items() if v is not None})
        try:
            self._send(payload)
        except Exception:  # noqa: BLE001 - never let emit crash the agent
            pass


class CollectingEmitter(EventEmitter):
    """Stores every event in a list (used by tests and the blocking run)."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, event_type: str, **data: Any) -> None:
        payload = {"event": event_type, "ts": time.time()}
        payload.update(data)
        self.events.append(payload)


class LoggingEmitter(EventEmitter):

    def emit(self, event_type: str, **data: Any) -> None:
        if event_type in (EV_THINKING, EV_CONTENT):
            text = data.get("text") or ""
            if text:
                end = "\n" if event_type == EV_CONTENT else ""
                print(text, end=end, flush=True)
            return
        if event_type == EV_NODE:
            print(f"\n[node] {data.get('node_id')} ({data.get('role')})", flush=True)
        elif event_type == EV_TOOL_CALL:
            print(f"\n[tool_call] {data.get('name')} {data.get('arguments')}", flush=True)
        elif event_type == EV_TOOL_RESULT:
            print(f"[tool_result] {str(data.get('result'))[:200]}", flush=True)
        elif event_type in (EV_STDOUT, EV_STDERR):
            print(f"[{event_type}] {data.get('line')}", flush=True)
        elif event_type == EV_DONE:
            print(f"\n[done] success={data.get('success')}", flush=True)
        elif event_type == EV_ERROR:
            print(f"\n[error] {data.get('message')}", flush=True)


class _NoopEmitter(EventEmitter):
    """Drops all events (used by the non-streaming ``Agent.run``)."""

    def emit(self, event_type: str, **data: Any) -> None:
        pass


def get_emitter() -> Optional[EventEmitter]:
    return _current_emitter.get()


def set_emitter(emitter: Optional[EventEmitter]) -> Any:
    """Set the context-local emitter; returns the token for reset."""
    return _current_emitter.set(emitter)


def reset_emitter(token: Any) -> None:
    _current_emitter.reset(token)


class _EventLogHandler(logging.Handler):
    """Forwards log records to the current emitter as stdout/stderr events."""

    def emit(self, record: logging.LogRecord) -> None:  # type: ignore[override]
        emitter = _current_emitter.get()
        if emitter is None:
            return
        level = record.levelno
        line = self.format(record)
        if level >= logging.ERROR:
            emitter.emit(EV_STDERR, line=line)
        else:
            emitter.emit(EV_STDOUT, line=line)
