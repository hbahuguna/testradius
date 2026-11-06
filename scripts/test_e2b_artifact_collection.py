#!/usr/bin/env python3
"""Demo for STORY-E2B-004.1: Screenshot & Artifact Collection from sandbox.

Simulates sandbox artifacts and demonstrates downloading/normalizing them into
artifacts/run-<id>/ with a manifest.json.

Usage:
  python scripts/test_e2b_artifact_collection.py
  python scripts/test_e2b_artifact_collection.py --out /tmp/tr-artifacts-demo
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.e2b.artifacts import collect_sandbox_artifacts
from harness.sandbox.base import BaseSandboxProvider


class DemoSandboxProvider(BaseSandboxProvider):
    def __init__(self):
        self.files: dict[tuple[str, str], bytes] = {}
        sid = "sbx-demo-artifacts"
        self.files[(sid, "/home/user/artifacts/step_results.json")] = json.dumps(
            {
                "plan_id": "PLAN-DEMO",
                "status": "PASSED",
                "steps": [
                    {"step_id": "STEP-01", "status": "PASSED", "screenshot": "/home/user/artifacts/STEP-01.png"},
                    {"step_id": "STEP-02", "status": "PASSED", "screenshot": "/home/user/artifacts/STEP-02.png"},
                ],
            }
        ).encode()
        self.files[(sid, "/home/user/artifacts/STEP-01.png")] = b"\x89PNG\r\n\x1a\n(demo screenshot 1)"
        self.files[(sid, "/home/user/artifacts/STEP-02.png")] = b"\x89PNG\r\n\x1a\n(demo screenshot 2)"
        self.files[(sid, "/home/user/artifacts/trace.zip")] = b"PK\x03\x04(demo trace)"
        self.files[(sid, "/home/user/artifacts/console.log")] = b"[info] page loaded\n[warn] minor layout shift\n"
        self.files[(sid, "/home/user/artifacts/network.json")] = json.dumps([{"url": "https://testradius.dev", "status": 200}]).encode()

    def create(self, template: str = "base", timeout: int = 300, **kwargs) -> str:
        return "sbx-demo-artifacts"

    def kill(self, sandbox_id: str) -> bool:
        return True

    def run_command(self, sandbox_id: str, command: str, timeout: int = 60) -> dict:
        if command.startswith("find "):
            existing = [p for (s, p), _ in self.files.items() if s == sandbox_id and p.startswith("/home/user/artifacts")]
            return {"stdout": "\n".join(sorted(existing)), "stderr": "", "exit_code": 0}
        return {"stdout": "", "stderr": "", "exit_code": 0}

    def upload_file(self, sandbox_id: str, path: str, content: bytes) -> bool:
        self.files[(sandbox_id, path)] = content
        return True

    def download_file(self, sandbox_id: str, path: str) -> bytes:
        return self.files.get((sandbox_id, path), b"")

    def is_running(self, sandbox_id: str) -> bool:
        return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("artifacts/demo_e2b_artifacts"))
    args = parser.parse_args()

    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True, exist_ok=True)

    provider = DemoSandboxProvider()
    manifest = collect_sandbox_artifacts(
        provider=provider,
        sandbox_id="sbx-demo-artifacts",
        run_id="run-demo-0041",
        artifacts_root=args.out,
    )

    run_dir = args.out / "run-demo-0041"
    print("=== STORY-E2B-004.1: Artifact Collection Demo ===\n")
    print(f"Run dir: {run_dir}")
    print(f"Manifest: {run_dir / 'manifest.json'}")
    print(f"Artifacts collected: {len(manifest.artifacts)}")
    for a in manifest.artifacts:
        print(f"  - [{a.type}] {a.filename} <= {a.remote_path} ({a.size_bytes} bytes)")

    saved = json.loads((run_dir / "manifest.json").read_text())
    assert saved["run_id"] == "run-demo-0041"
    assert any(x["type"] == "screenshot" for x in saved["artifacts"])
    assert any(x["type"] == "trace" for x in saved["artifacts"])
    assert any(x["type"] == "console" or x["type"] == "log" for x in saved["artifacts"])
    assert any(x["type"] == "network" or x["filename"] == "network.json" for x in saved["artifacts"])
    assert all("path" in x and "type" in x for x in saved["artifacts"])

    print("\n✓ STORY-E2B-004.1 DEMO PASSED: Artifacts synced locally with manifest.")

    # Clean demo output
    shutil.rmtree(args.out, ignore_errors=True)


if __name__ == "__main__":
    main()
