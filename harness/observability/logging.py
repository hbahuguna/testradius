"""Structured JSON logging."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class LogEvent:
    ts: str
    level: str
    message: str
    run_id: Optional[str] = None
    component: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class StructuredLogger:
    def __init__(self, run_id: Optional[str] = None, component: str = "harness"):
        self.run_id = run_id
        self.component = component

    def log(self, level: str, message: str, **context) -> LogEvent:
        event = LogEvent(
            ts=datetime.now(timezone.utc).isoformat(),
            level=level,
            message=message,
            run_id=self.run_id,
            component=self.component,
            context=context,
        )
        print(event.to_json(), file=sys.stdout)
        return event

    def info(self, message: str, **context) -> LogEvent:
        return self.log("info", message, **context)

    def warn(self, message: str, **context) -> LogEvent:
        return self.log("warn", message, **context)

    def error(self, message: str, **context) -> LogEvent:
        return self.log("error", message, **context)

    def debug(self, message: str, **context) -> LogEvent:
        return self.log("debug", message, **context)
