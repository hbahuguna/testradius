import json
import time
from pathlib import Path


class EvidenceCapture:
    def __init__(self, base_dir: str = "artifacts"):
        self.base_dir = Path(base_dir)
        self.run_id = f"run-{int(time.time())}"
        self.run_dir = self.base_dir / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.manifest = {"run_id": self.run_id, "artifacts": []}

    def screenshot(self, name: str = "screenshot.png") -> Path:
        p = self.run_dir / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        self.manifest["artifacts"].append({"type": "screenshot", "path": str(p)})
        return p

    def console_log(self, text: str) -> Path:
        p = self.run_dir / "console.log"
        p.write_text(text)
        self.manifest["artifacts"].append({"type": "console", "path": str(p)})
        return p

    def network_trace(self) -> Path:
        p = self.run_dir / "network.json"
        p.write_text(json.dumps([]))
        self.manifest["artifacts"].append({"type": "network", "path": str(p)})
        return p

    def trace(self) -> Path:
        p = self.run_dir / "trace.zip"
        p.write_bytes(b"PK")
        self.manifest["artifacts"].append({"type": "trace", "path": str(p)})
        return p

    def save_manifest(self) -> Path:
        p = self.run_dir / "manifest.json"
        p.write_text(json.dumps(self.manifest, indent=2))
        return p
