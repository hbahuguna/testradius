"""Run manifest schema."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class RunManifest:
    manifest_version: str = "1.0"
    run_id: str = ""
    target: str = ""
    status: str = "CREATED"
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_ms: Optional[int] = None
    model: Optional[str] = None
    plan_id: Optional[str] = None
    approved_by: Optional[str] = None
    artifacts: List[Dict[str, str]] = field(default_factory=list)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def mark_started(self):
        if not self.started_at:
            self.started_at = datetime.now(timezone.utc).isoformat()

    def mark_finished(self, status: str = "COMPLETED"):
        self.status = status
        self.ended_at = datetime.now(timezone.utc).isoformat()
        if self.started_at:
            try:
                start = datetime.fromisoformat(self.started_at.replace("Z", "+00:00"))
                end = datetime.fromisoformat(self.ended_at.replace("Z", "+00:00"))
                self.duration_ms = int((end - start).total_seconds() * 1000)
            except Exception:
                pass

    def add_artifact(self, kind: str, path: str):
        self.artifacts.append({"type": kind, "path": path})
        return self

    def add_step(self, step_id: str, title: str, status: str = "PENDING", **extra):
        self.steps.append({"id": step_id, "title": title, "status": status, **extra})
        return self

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path

    @classmethod
    def load(cls, path: Path) -> "RunManifest":
        data = json.loads(path.read_text())
        return cls(**data)
