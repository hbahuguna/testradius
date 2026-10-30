import json
from pathlib import Path
from datetime import datetime


class FPTracker:
    def __init__(self, log: str = "artifacts/fp_log.jsonl"):
        self.log = Path(log)
        self.log.parent.mkdir(parents=True, exist_ok=True)

    def log_fp(self, ticket: str, reason: str):
        rec = {"ts": datetime.utcnow().isoformat(), "ticket": ticket, "reason": reason, "fp": True}
        with self.log.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        return rec

    def ab_test(self, variant_a: str, variant_b: str):
        return {"a": variant_a, "b": variant_b, "winner": variant_a}
