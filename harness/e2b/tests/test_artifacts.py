"""Tests for STORY-E2B-004.1: sandbox artifact collection and manifest."""
import json
from pathlib import Path

from harness.e2b.artifacts import SandboxArtifactCollector, classify_artifact, collect_sandbox_artifacts
from harness.sandbox.base import BaseSandboxProvider


class MockSandboxProvider(BaseSandboxProvider):
    def __init__(self):
        self.files: dict[tuple[str, str], bytes] = {}
        self.commands: list[str] = []

    def create(self, template: str = "base", timeout: int = 300, **kwargs) -> str:
        return "sbx-art-1"

    def kill(self, sandbox_id: str) -> bool:
        return True

    def run_command(self, sandbox_id: str, command: str, timeout: int = 60) -> dict:
        self.commands.append(command)
        if command.startswith("find "):
            # Return known evidence-like files
            paths = [
                "/home/user/artifacts/step_results.json",
                "/home/user/artifacts/S1.png",
                "/home/user/artifacts/S2.png",
                "/home/user/artifacts/trace.zip",
                "/home/user/artifacts/console.log",
                "/home/user/artifacts/network.json",
            ]
            existing = [p for p in paths if (sandbox_id, p) in self.files]
            return {"stdout": "\n".join(existing), "stderr": "", "exit_code": 0}
        return {"stdout": "", "stderr": "", "exit_code": 0}

    def upload_file(self, sandbox_id: str, path: str, content: bytes) -> bool:
        self.files[(sandbox_id, path)] = content
        return True

    def download_file(self, sandbox_id: str, path: str) -> bytes:
        return self.files.get((sandbox_id, path), b"")

    def is_running(self, sandbox_id: str) -> bool:
        return True


def test_classify_artifact():
    assert classify_artifact("/a/b/S1.png") == "screenshot"
    assert classify_artifact("/a/trace.zip") == "trace"
    assert classify_artifact("/a/video.webm") == "video"
    assert classify_artifact("/a/console.log") == "console"
    assert classify_artifact("/a/network.json") == "network"
    assert classify_artifact("/a/step_results.json") == "result"


def test_collect_sandbox_artifacts_downloads_and_creates_manifest(tmp_path):
    provider = MockSandboxProvider()
    sid = "sbx-art-1"
    step_results = {
        "plan_id": "P",
        "status": "PASSED",
        "steps": [
            {"step_id": "S1", "screenshot": "/home/user/artifacts/S1.png", "status": "PASSED"},
            {"step_id": "S2", "screenshot": "/home/user/artifacts/S2.png", "status": "PASSED"},
        ],
    }
    provider.files[(sid, "/home/user/artifacts/step_results.json")] = json.dumps(step_results).encode("utf-8")
    provider.files[(sid, "/home/user/artifacts/S1.png")] = b"png1"
    provider.files[(sid, "/home/user/artifacts/S2.png")] = b"png2"
    provider.files[(sid, "/home/user/artifacts/trace.zip")] = b"PKtrace"
    provider.files[(sid, "/home/user/artifacts/console.log")] = b"logline\n"
    provider.files[(sid, "/home/user/artifacts/network.json")] = b"[]"

    manifest = collect_sandbox_artifacts(
        provider=provider,
        sandbox_id=sid,
        run_id="run-art-001",
        artifacts_root=tmp_path / "artifacts",
    )

    run_dir = tmp_path / "artifacts" / "run-art-001"
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "S1.png").read_bytes() == b"png1"
    assert (run_dir / "S2.png").read_bytes() == b"png2"
    assert (run_dir / "trace.zip").read_bytes() == b"PKtrace"
    assert (run_dir / "console.log").read_bytes() == b"logline\n"
    assert (run_dir / "network.json").read_bytes() == b"[]"
    assert (run_dir / "step_results.json").exists()

    saved = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert saved["run_id"] == "run-art-001"
    assert saved["source"]["sandbox_id"] == sid
    types = {a["type"] for a in saved["artifacts"]}
    assert {"screenshot", "trace", "console", "network", "result"}.issubset(types)
    # Legacy-compatible keys
    assert all("type" in a and "path" in a for a in saved["artifacts"])
    # Extended metadata
    assert any(a.get("remote_path") == "/home/user/artifacts/S1.png" for a in saved["artifacts"])
    assert any(a.get("sha256") for a in saved["artifacts"])


def test_collector_handles_missing_files_gracefully(tmp_path):
    provider = MockSandboxProvider()
    manifest = SandboxArtifactCollector(
        provider, "sbx-missing", "run-missing", artifacts_root=tmp_path
    ).collect(remote_paths=["/nope.png", "/also/nope.zip"])
    assert (tmp_path / "run-missing" / "manifest.json").exists()
    assert manifest.artifacts == []
