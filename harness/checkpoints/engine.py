import json
import os
from pathlib import Path
from datetime import datetime


class CheckpointEngine:
    def __init__(self, log_path: str = "artifacts/checkpoints.jsonl"):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def request_approval(self, step: str, context: dict) -> bool:
        approved = os.environ.get("HARNESS_APPROVE", "0") == "1"
        rec = {"ts": datetime.utcnow().isoformat(), "step": step, "approved": approved, "context": context}
        with self.log_path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        return approved

    def require_approval(self, step: str, context: dict):
        if not self.request_approval(step, context):
            raise PermissionError(f"Checkpoint not approved: {step}")
        return True
