"""Approval flow with audit logging."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class AuditEntry:
    ts: str
    action: str
    actor: str
    run_id: str
    detail: str = ""
    ip: Optional[str] = None


@dataclass
class ApprovalState:
    run_id: str
    approved: bool = False
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    audit_log: List[AuditEntry] = field(default_factory=list)

    def require_approval(self):
        if not self.approved:
            raise PermissionError(f"Run {self.run_id} blocked: approval required before execution")

    def approve(self, actor: str, detail: str = ""):
        if self.approved:
            raise ValueError("Run already approved")
        self.approved = True
        self.approved_by = actor
        self.approved_at = datetime.now(timezone.utc).isoformat()
        self.audit_log.append(
            AuditEntry(
                ts=self.approved_at,
                action="APPROVE",
                actor=actor,
                run_id=self.run_id,
                detail=detail,
            )
        )
        return self

    def revoke(self, actor: str, detail: str = ""):
        if not self.approved:
            raise ValueError("Run not approved")
        self.approved = False
        ts = datetime.now(timezone.utc).isoformat()
        self.approved_by = None
        self.approved_at = None
        self.audit_log.append(AuditEntry(ts=ts, action="REVOKE", actor=actor, run_id=self.run_id, detail=detail))
        return self

    def export_audit(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "run_id": self.run_id,
            "approved": self.approved,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "audit_log": [asdict(e) for e in self.audit_log],
        }
        path.write_text(json.dumps(data, indent=2))
        return path


class ApprovalRegistry:
    def __init__(self):
        self._states: Dict[str, ApprovalState] = {}

    def get(self, run_id: str) -> ApprovalState:
        if run_id not in self._states:
            self._states[run_id] = ApprovalState(run_id=run_id)
        return self._states[run_id]

    def enforce(self, run_id: str):
        self.get(run_id).require_approval()
        return True
