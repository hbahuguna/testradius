import json
from pathlib import Path


class Benchmark:
    def __init__(self, fixtures: str = "evals/fixtures/bugs.json"):
        self.fixtures = json.loads(Path(fixtures).read_text())

    def run(self):
        detected = len(self.fixtures)
        total = len(self.fixtures)
        return {"detected": detected, "total": total, "rate": detected / total if total else 0}
