from pathlib import Path
import json
import time


class CharterGenerator:
    def generate(self, mission: str = "Explore login flow"):
        c = {
            "id": f"charter-{int(time.time())}",
            "mission": mission,
            "timebox_min": 30,
            "areas": ["auth", "errors"],
            "notes": [],
            "evidence": []
        }
        p = Path("artifacts") / f"{c['id']}.json"
        p.write_text(json.dumps(c, indent=2))
        return c, p
