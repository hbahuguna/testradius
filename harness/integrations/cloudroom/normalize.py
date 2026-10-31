"""Normalize Cloud Room artifacts to harness evidence structure."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict


class EvidenceNormalizer:
    """Normalize artifacts from Cloud Room to match harness structure."""

    def normalize(self, source_dir: Path, run_id: str, artifacts_dir: Path) -> Dict[str, Any]:
        """Normalize artifacts to expected structure."""
        target_dir = artifacts_dir / f"run-{run_id}"
        target_dir.mkdir(parents=True, exist_ok=True)
        screenshots_dir = target_dir / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)

        result = {
            "run_id": run_id,
            "screenshots": [],
            "video": None,
            "traces": [],
            "logs": [],
        }

        if not source_dir.exists():
            return result

        for f in source_dir.rglob("*"):
            if not f.is_file():
                continue
            name = f.name.lower()
            if name.endswith((".png", ".jpg", ".jpeg")):
                dest = screenshots_dir / f.name
                shutil.copy2(f, dest)
                result["screenshots"].append(str(dest))
            elif name.endswith((".webm", ".mp4")):
                dest = target_dir / f"run-{run_id}.webm" if name.endswith(".webm") else target_dir / f.name
                if name.endswith(".webm") and not dest.name.endswith(f"run-{run_id}.webm"):
                    dest = target_dir / f"run-{run_id}.webm"
                shutil.copy2(f, dest)
                result["video"] = str(dest)
            elif name.endswith((".json", ".zip")) and ("trace" in name or "log" in name):
                dest = target_dir / f.name
                shutil.copy2(f, dest)
                if "trace" in name:
                    result["traces"].append(str(dest))
                else:
                    result["logs"].append(str(dest))

        # Create manifest if not exists
        manifest_path = target_dir / "manifest.json"
        if not manifest_path.exists():
            manifest = {
                "run_id": run_id,
                "screenshots": [Path(s).name for s in result["screenshots"]],
                "video": Path(result["video"]).name if result["video"] else None,
                "traces": [Path(t).name for t in result["traces"]],
                "console": [],
                "network": [],
            }
            manifest_path.write_text(json.dumps(manifest, indent=2))

        return result
