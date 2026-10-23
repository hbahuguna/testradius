"""Data-driven orchestrator driving all seven phases with stubs."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from cell.models import Phase, RunStatus
from cell.runs.state import PHASE_ORDER, Run, RunStore


class Orchestrator:
    def __init__(
        self,
        store: RunStore,
        state_dir: str | None = None,
        agent_factory: Callable[[Run], object] | None = None,
    ):
        self.store = store
        self.agent_factory = agent_factory
        self._tasks: dict[str, asyncio.Task] = {}
        self._events: dict[str, list[dict]] = {}
        self._seq: dict[str, int] = {}
        self._event_dir = Path(state_dir) / "events" if state_dir else None
        if self._event_dir:
            self._event_dir.mkdir(parents=True, exist_ok=True)
            self._load_all_events()

    def _event_path(self, run_id: str) -> Path | None:
        return self._event_dir / f"{run_id}.jsonl" if self._event_dir else None

    def _emit(self, run_id: str, event_type: str, phase: Phase | None, payload: dict) -> dict:
        self._seq[run_id] = self._seq.get(run_id, 0) + 1
        event = {
            "schema_version": "1",
            "run_id": run_id,
            "seq": self._seq[run_id],
            "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "type": event_type,
            "phase": phase.value if phase else None,
            "payload": payload,
        }
        self._events.setdefault(run_id, []).append(event)
        path = self._event_path(run_id)
        if path:
            with path.open("a") as handle:
                handle.write(json.dumps(event) + "\n")
        return event

    def get_events(self, run_id: str, since_seq: int = 0) -> list[dict]:
        events = self._events.get(run_id)
        if events is None:
            events = self._load_events(run_id)
        return [event for event in events if event["seq"] > since_seq]

    def _load_all_events(self) -> None:
        for path in self._event_dir.glob("*.jsonl"):
            self._load_events(path.stem)

    def _load_events(self, run_id: str) -> list[dict]:
        path = self._event_path(run_id)
        events: list[dict] = []
        if path and path.exists():
            for line in path.read_text().splitlines():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            self._events[run_id] = events
            self._seq[run_id] = max((event["seq"] for event in events), default=0)
        return events

    def resume_incomplete(self) -> None:
        for run in self.store.list():
            if run.status in (RunStatus.QUEUED, RunStatus.RUNNING) and not run.cancelled:
                run.status = RunStatus.QUEUED
                self.start(run)

    def start(self, run: Run) -> None:
        task = self._tasks.get(run.run_id)
        if task and not task.done():
            return
        self._tasks[run.run_id] = asyncio.create_task(self._run(run.run_id))

    async def cancel(self, run_id: str) -> bool:
        run = self.store.get(run_id)
        if not run:
            return False
        if run.status in (
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.TIMED_OUT,
        ):
            return False
        run.cancelled = True
        self._emit(run_id, "log", None, {"event": "run.cancelled"})
        run.status = RunStatus.CANCELLED
        run.updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        self.store.save()
        task = self._tasks.get(run_id)
        if task and not task.done():
            task.cancel()
        return True

    async def _run(self, run_id: str) -> None:
        run = self.store.get(run_id)
        if not run:
            return
        if run.policy.get("runtime") == "agent" and self.agent_factory is not None:
            await self._run_agent(run_id, run)
            return

        run.status = RunStatus.RUNNING
        run.updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        self.store.save()
        self._emit(run_id, "log", None, {"event": "run.started"})

        start_index = 0
        if run.phase is not None:
            start_index = PHASE_ORDER.index(run.phase) + 1
        delay = max(0.0, min(float(run.policy.get("stub_delay_ms", 10)) / 1000.0, 1.0))

        try:
            for phase in PHASE_ORDER[start_index:]:
                if run.cancelled:
                    return
                run.phase = phase
                run.updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                self.store.save()
                self._emit(run_id, "phase", phase, {"event": "phase.started"})
                await asyncio.sleep(delay)
                self._emit(run_id, "phase", phase, {"event": "phase.completed", "stub": True})
            if run.cancelled:
                return
            self._emit(run_id, "log", Phase.REPORT, {"event": "run.completed"})
            run.status = RunStatus.SUCCEEDED
            run.updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            self.store.save()
        except asyncio.CancelledError:
            run.status = RunStatus.CANCELLED
            run.updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            self.store.save()
        except Exception:
            self._emit(run_id, "log", run.phase, {"event": "run.failed"})
            run.status = RunStatus.FAILED
            run.updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            self.store.save()

    async def _run_agent(self, run_id: str, run: Run) -> None:
        """Run the Sprint 3 planner/executor while preserving phase events."""

        from cell.agent.executor import AgentCancelled

        session = self.agent_factory(run)  # type: ignore[misc]
        started_at = time.monotonic()
        run.status = RunStatus.RUNNING
        run.updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        self.store.save()
        self._emit(run_id, "log", None, {"event": "run.started"})
        plan = None
        try:
            for phase in PHASE_ORDER:
                if run.cancelled:
                    return
                run.phase = phase
                run.updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                self.store.save()
                self._emit(run_id, "phase", phase, {"event": "phase.started"})
                if phase == Phase.GENERATE:
                    goal = run.goal or f"{run.scope} for {run.repo}@{run.commit}"
                    plan = await session.plan(goal)  # type: ignore[attr-defined]
                    metadata = getattr(session, "context_metadata", None)
                    self._emit(
                        run_id,
                        "log",
                        phase,
                        {
                            "event": "context.retrieved",
                            **(metadata() if callable(metadata) else {}),
                        },
                    )
                    self._emit(
                        run_id,
                        "step",
                        phase,
                        {"event": "plan.created", "plan": plan.to_dict()},
                    )
                    self._emit(run_id, "phase", phase, {"event": "phase.completed"})
                elif phase == Phase.EXECUTE:
                    if plan is None:
                        raise RuntimeError("agent plan missing before execute")
                    emit_agent_event = lambda event_type, payload, phase=phase: self._emit(  # noqa: E731
                        run_id, event_type, phase, payload
                    )

                    result = await session.execute(  # type: ignore[attr-defined]
                        plan,
                        is_cancelled=lambda: run.cancelled,
                        emit=emit_agent_event,
                    )
                    self._emit(run_id, "phase", phase, {"event": "phase.completed"})
                    metrics = {
                        "steps": len(result.steps),
                        "tokens": plan.usage.total,
                        "tool_calls": len(getattr(session.registry, "calls", [])),
                        "duration_ms": int((time.monotonic() - started_at) * 1000),
                    }
                    self._emit(
                        run_id,
                        "verdict",
                        phase,
                        {"event": "run.verdict", **result.to_dict(), "metrics": metrics},
                    )
                    if result.verdict != "passed":
                        run.status = RunStatus.FAILED
                        run.updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                        self.store.save()
                        return
                else:
                    self._emit(run_id, "phase", phase, {"event": "phase.completed"})
            self._emit(run_id, "log", Phase.REPORT, {"event": "run.completed"})
            run.status = RunStatus.SUCCEEDED
            run.updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            self.store.save()
        except AgentCancelled:
            run.status = RunStatus.CANCELLED
            run.updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            self.store.save()
        except asyncio.CancelledError:
            run.status = RunStatus.CANCELLED
            run.updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            self.store.save()
        except Exception as exc:
            self._emit(
                run_id,
                "log",
                run.phase,
                {
                    "event": "run.failed",
                    "kind": getattr(exc, "code", type(exc).__name__),
                    "reason": str(exc),
                },
            )
            run.status = RunStatus.FAILED
            run.updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            self.store.save()
        finally:
            close = getattr(session, "close", None)
            if close is not None:
                outcome = close()
                if inspect.isawaitable(outcome):
                    await outcome
