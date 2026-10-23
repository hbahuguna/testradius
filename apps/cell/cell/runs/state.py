"""Run state with optional JSON persistence.

In Docker the directory is the writable ``/workspace`` volume; tests get a
fresh temporary directory per app instance. Persistence is what makes a
kill/restart resume plausible in Sprint 2.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cell.models import Phase, RunStatus

PHASE_ORDER = [
    Phase.ISOLATE,
    Phase.SELECT,
    Phase.GENERATE,
    Phase.EXECUTE,
    Phase.PROVE,
    Phase.GATE,
    Phase.REPORT,
]


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class Run:
    run_id: str
    repo: str
    commit: str
    scope: str
    policy: dict[str, Any]
    goal: str | None = None
    status: RunStatus = RunStatus.QUEUED
    phase: Phase | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    cancelled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "repo": self.repo,
            "commit": self.commit,
            "scope": self.scope,
            "policy": self.policy,
            "goal": self.goal,
            "status": self.status.value,
            "phase": self.phase.value if self.phase else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "cancelled": self.cancelled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Run:
        return cls(
            run_id=data["run_id"],
            repo=data["repo"],
            commit=data["commit"],
            scope=data["scope"],
            policy=data.get("policy") or {},
            goal=data.get("goal"),
            status=RunStatus(data["status"]),
            phase=Phase(data["phase"]) if data.get("phase") else None,
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            cancelled=bool(data.get("cancelled")),
        )


class RunStore:
    def __init__(self, state_dir: str | None = None):
        self._dir = Path(state_dir) if state_dir else Path(tempfile.mkdtemp(prefix="cell-state-"))
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "runs.json"
        self._runs: dict[str, Run] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        for item in data.get("runs", []):
            try:
                run = Run.from_dict(item)
            except (KeyError, TypeError, ValueError):
                continue
            self._runs[run.run_id] = run

    def save(self) -> None:
        payload = {"runs": [run.to_dict() for run in self._runs.values()]}
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self._path)

    def create(self, run: Run) -> Run:
        self._runs[run.run_id] = run
        self.save()
        return run

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def list(self) -> list[Run]:
        return list(self._runs.values())
