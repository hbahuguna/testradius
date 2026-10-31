"""Translate Cloud Room events to harness live state."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


class LiveStateTranslator:
    """Translate Cloud Room journal to harness live execution state."""

    def translate(self, journal: Dict[str, Any], run_id: str, target: str) -> Dict[str, Any]:
        events = journal.get("events", []) or journal.get("logs", []) or []
        steps = []
        logs = []
        current_step_id = None
        completed = 0

        for i, ev in enumerate(events):
            if isinstance(ev, dict):
                msg = ev.get("message") or ev.get("msg") or str(ev)
                ts = ev.get("timestamp") or ev.get("ts") or datetime.now(timezone.utc).isoformat()
                logs.append({
                    "id": f"log-{i}",
                    "ts": ts,
                    "level": ev.get("level", "info"),
                    "message": msg,
                })
                if "step" in msg.lower() or "test" in msg.lower():
                    step_id = f"s{i}"
                    steps.append({
                        "id": step_id,
                        "testCaseId": f"TC{i+1:02d}",
                        "title": msg[:80],
                        "status": "RUNNING" if i == len(events) - 1 else "COMPLETED",
                    })
                    if i == len(events) - 1 and "completed" not in msg.lower() and "done" not in msg.lower():
                        current_step_id = step_id
                    else:
                        completed += 1

        if not steps:
            steps = [{"id": "s1", "testCaseId": "TC01", "title": "Cloud Room execution", "status": "RUNNING"}]
            current_step_id = "s1"

        return {
            "runId": run_id,
            "target": target,
            "status": "RUNNING" if current_step_id else "COMPLETED",
            "currentStepId": current_step_id,
            "progress": {"completed": completed or len(steps), "total": len(steps), "failed": 0},
            "steps": steps,
            "logs": logs[-100:],
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
