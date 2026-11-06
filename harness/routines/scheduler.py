"""Routine scheduling and execution hooks for E2B runs (STORY-E2B-006.2).

Provides configurable cadence metadata, run history, notification callbacks,
and E2B-oriented routine execution. Supports simple in-process cadence checks
(@hourly/@daily/@weekly/interval:<seconds>) and stores raw cron strings for
external schedulers.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

NotificationCallback = Callable[[Dict[str, Any]], None]
RoutineRunner = Callable[["RoutineConfig"], Dict[str, Any]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        # support Z
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


@dataclass
class RoutineConfig:
    name: str
    cadence: str = "manual"  # @hourly|@daily|@weekly|interval:<seconds>|manual|<cron string>
    executor_type: str = "e2b"
    target_url: str = ""
    plan: Optional[Union[Dict[str, Any], str, Path]] = None
    enabled: bool = True
    timeout_seconds: int = 600
    metadata: Dict[str, Any] = field(default_factory=dict)
    notify_on: Sequence[str] = field(default_factory=lambda: ["completed", "failed"])  # events to notify

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["notify_on"] = list(self.notify_on)
        return d


class RoutineHistory:
    def __init__(self, path: Union[str, Path] = "artifacts/routine_history.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: Dict[str, Any]) -> Dict[str, Any]:
        rec = {**record}
        rec.setdefault("ts", _utc_now())
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        return rec

    def records(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out: List[Dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out

    def last_for(self, name: str, event: Optional[str] = None) -> Optional[Dict[str, Any]]:
        run_events = {"run_started", "run_completed", "run_failed"}
        for rec in reversed(self.records()):
            if rec.get("name") != name:
                continue
            if event:
                if rec.get("event") != event and rec.get("status") != event:
                    continue
            else:
                # default: last actual run record (ignore registered/scheduled metadata)
                if rec.get("event") not in run_events and not rec.get("run_at") and not rec.get("completed_at"):
                    continue
            return rec
        return None


class Scheduler:
    """Routine scheduler/runner with history and notifications.

    Backward compatible with legacy `schedule(name, cron=...)` and `run_now(name)`.
    """

    def __init__(
        self,
        history: Union[str, Path] = "artifacts/routine_history.jsonl",
        *,
        runner: Optional[RoutineRunner] = None,
        notifiers: Optional[Sequence[NotificationCallback]] = None,
    ):
        self.history = RoutineHistory(history)
        self.runner = runner
        self.notifiers = list(notifiers or [])
        self.routines: Dict[str, RoutineConfig] = {}

    # ---- backward-compatible API ----
    def schedule(self, name: str, cron: str = "0 2 * * *"):
        cfg = self.routines.get(name) or RoutineConfig(name=name, cadence=cron)
        cfg.cadence = cron
        self.routines[name] = cfg
        rec = {"event": "scheduled", "name": name, "cron": cron, "cadence": cron, "scheduled_at": _utc_now()}
        self.history.append(rec)
        return rec

    def run_now(self, name: str):
        cfg = self.routines.get(name)
        if self.runner is None and (cfg is None or (not cfg.plan and not cfg.target_url)):
            # Legacy/simple behavior: no execution runner/configured E2B plan
            rec = {"name": name, "run_at": _utc_now(), "status": "ok"}
            self.history.append({**rec, "event": "run_completed"})
            self.notify({"event": "run_completed", "routine": name, "status": "ok"})
            return rec
        cfg = cfg or RoutineConfig(name=name)
        rec = self.run_routine(cfg)
        rec.setdefault("run_at", rec.get("started_at"))
        return rec

    # ---- E2B-oriented API ----
    def register(self, routine: RoutineConfig) -> RoutineConfig:
        self.routines[routine.name] = routine
        self.history.append({"event": "registered", "name": routine.name, "routine": routine.to_dict()})
        return routine

    def add_notifier(self, callback: NotificationCallback) -> None:
        self.notifiers.append(callback)

    def notify(self, event: Dict[str, Any]) -> None:
        for cb in self.notifiers:
            try:
                cb(event)
            except Exception:
                # notifications must not break routine execution
                pass

    def is_due(self, routine: RoutineConfig, now: Optional[datetime] = None) -> bool:
        if not routine.enabled:
            return False
        cadence = (routine.cadence or "manual").strip().lower()
        if cadence in {"manual", ""}:
            return False
        now = now or datetime.now(timezone.utc)
        last = self.history.last_for(routine.name)
        last_ts = _parse_ts((last or {}).get("ts") or (last or {}).get("run_at") or (last or {}).get("completed_at"))
        if cadence == "@hourly":
            return last_ts is None or (now - last_ts).total_seconds() >= 3600
        if cadence == "@daily":
            return last_ts is None or (now - last_ts).total_seconds() >= 86400
        if cadence == "@weekly":
            return last_ts is None or (now - last_ts).total_seconds() >= 604800
        if cadence.startswith("interval:"):
            try:
                secs = float(cadence.split(":", 1)[1])
            except Exception:
                secs = 0
            return secs > 0 and (last_ts is None or (now - last_ts).total_seconds() >= secs)
        # raw cron expression: in-process due-check not implemented; treat as external scheduler
        return False

    def run_routine(self, routine: RoutineConfig) -> Dict[str, Any]:
        started_at = _utc_now()
        self.history.append({"event": "run_started", "name": routine.name, "cadence": routine.cadence, "executor_type": routine.executor_type, "started_at": started_at})
        self.notify({"event": "run_started", "routine": routine.name, "started_at": started_at})
        try:
            if self.runner is not None:
                result = self.runner(routine)
            else:
                result = self._default_e2b_run(routine)
            status = str((result or {}).get("status") or "unknown")
            rec = {
                "event": "run_completed",
                "name": routine.name,
                "status": status.lower() if status else "ok",
                "run_at": started_at,  # legacy field
                "started_at": started_at,
                "completed_at": _utc_now(),
                "executor_type": routine.executor_type,
                "result": result,
            }
            self.history.append(rec)
            if status.lower() in {str(x).lower() for x in routine.notify_on} or ("completed" in routine.notify_on and status.upper().startswith("COMPLETED")):
                self.notify({"event": "run_completed", "routine": routine.name, "status": status, "result": result})
            # legacy compatibility
            if "status" not in rec:
                rec["status"] = "ok"
            return rec
        except Exception as e:
            rec = {
                "event": "run_failed",
                "name": routine.name,
                "status": "failed",
                "run_at": started_at,
                "started_at": started_at,
                "completed_at": _utc_now(),
                "error": str(e),
                "executor_type": routine.executor_type,
            }
            self.history.append(rec)
            if "failed" in [str(x).lower() for x in routine.notify_on]:
                self.notify({"event": "run_failed", "routine": routine.name, "error": str(e)})
            return rec

    def _default_e2b_run(self, routine: RoutineConfig) -> Dict[str, Any]:
        if routine.executor_type != "e2b":
            return {"status": "SKIPPED", "reason": f"no default runner for executor_type={routine.executor_type}"}
        if not routine.plan or not routine.target_url:
            return {"status": "FAILED", "error": "E2B routine requires target_url and plan"}
        from ..e2b.orchestrator import E2BOrchestrationOptions, E2BOrchestrator

        opts = E2BOrchestrationOptions(
            run_id=f"{routine.name}-{int(time.time())}",
            target_url=routine.target_url,
            plan=routine.plan,
            timeout_seconds=routine.timeout_seconds,
            metadata={"routine": routine.name, **dict(routine.metadata)},
        )
        report = E2BOrchestrator().run(opts)
        return report.to_dict()

    def run_due(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        results = []
        for routine in self.routines.values():
            if self.is_due(routine, now=now):
                results.append(self.run_routine(routine))
        return results
