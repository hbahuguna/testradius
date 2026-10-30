import json
from pathlib import Path
from datetime import datetime


class Scheduler:
    def __init__(self, history: str = "artifacts/routine_history.jsonl"):
        self.history = Path(history)
        self.history.parent.mkdir(parents=True, exist_ok=True)

    def schedule(self, name: str, cron: str = "0 2 * * *"):
        rec = {"name": name, "cron": cron, "scheduled_at": datetime.utcnow().isoformat()}
        with self.history.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        return rec

    def run_now(self, name: str):
        rec = {"name": name, "run_at": datetime.utcnow().isoformat(), "status": "ok"}
        with self.history.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        return rec
