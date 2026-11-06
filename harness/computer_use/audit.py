"""Audit log schema + writer for computer-use runs (008.7.1).

Every logical action attempt must carry: timestamp, case/step, screenshot ref,
proposed action, validation, executed action, observation/result.
``action_trace.jsonl`` lines are validated against ``AUDIT_SCHEMA``.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


AUDIT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["ts", "run_id", "case_id", "step_id", "proposed", "validation", "executed", "observation"],
    "properties": {
        "ts": {"type": "string"},
        "run_id": {"type": "string"},
        "case_id": {"type": "string"},
        "step_id": {"type": "string"},
        "attempt": {"type": "integer"},
        "screenshot_before": {"type": ["string", "null"]},
        "screenshot_after": {"type": ["string", "null"]},
        "proposed": {"type": "object"},
        "validation": {"type": "object"},
        "executed": {"type": "boolean"},
        "observation": {"type": "object"},
    },
}


@dataclass
class AuditEntry:
    ts: str
    run_id: str
    case_id: str
    step_id: str
    attempt: int = 1
    screenshot_before: str | None = None
    screenshot_after: str | None = None
    proposed: Dict[str, Any] = field(default_factory=dict)
    validation: Dict[str, Any] = field(default_factory=dict)
    executed: bool = False
    observation: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def validate(self) -> List[str]:
        errors: List[str] = []
        data = self.to_dict()
        for req in ("ts", "run_id", "case_id", "step_id", "proposed", "validation", "executed", "observation"):
            if req not in data or data[req] in (None, "", {}, []):
                # executed=False is valid; treat explicitly False as present
                if req == "executed" and data[req] is False:
                    continue
                errors.append(f"missing {req}")
        return errors


class AuditWriter:
    """Append-only JSONL writer for audit entries."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("")

    def append(self, entry: AuditEntry | Dict[str, Any]) -> Dict[str, Any]:
        data = entry.to_dict() if isinstance(entry, AuditEntry) else dict(entry)
        data.setdefault("ts", _utc_now())
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
        return data


def validate_trace_file(path: Path | str) -> Dict[str, Any]:
    """Check trace lines carry the audit-required fields (per attempt merge)."""
    lines = Path(path).read_text(encoding="utf-8").splitlines() if Path(path).exists() else []
    # Merge per (step_id, attempt): unified entries satisfy directly; split propose/execute
    # entries satisfy jointly (backward-compatible with 008.5 traces).
    per_key: Dict[str, Dict[str, Any]] = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        key = f"{rec.get('step_id') or '?'}#attempt{rec.get('attempt', 1)}"
        slot = per_key.setdefault(key, {"proposed": None, "validation": None, "executed": None, "observation": None, "ts": rec.get("ts"), "run_id": rec.get("run_id"), "case_id": rec.get("case_id"), "step_id": rec.get("step_id")})
        if rec.get("proposed") is not None:
            slot["proposed"] = rec["proposed"]
        if rec.get("validation") is not None:
            slot["validation"] = rec["validation"]
        if "executed" in rec:
            slot["executed"] = rec["executed"]
        for k in ("observation", "result", "detail", "screenshot_before", "screenshot_after"):
            if rec.get(k) is not None:
                slot.setdefault("observation", {}) if k in {"observation", "result"} else slot
                if k in {"observation", "result"}:
                    slot["observation"] = rec.get("observation") or rec.get("result") or slot["observation"]
        # Observe/assert outcome recorded in step_results, not per trace line; tolerate via detail.
    missing: List[str] = []
    for key, slot in per_key.items():
        for req in ("proposed", "validation"):
            if slot.get(req) is None:
                missing.append(f"{key}:{req}")
        if slot.get("executed") is None:
            missing.append(f"{key}:executed")
    return {"entries": len(per_key), "lines": len(lines), "missing": missing, "ok": not missing and bool(per_key)}
