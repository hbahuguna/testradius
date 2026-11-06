"""Artifact collection from sandboxes (E2B/provider-agnostic) into harness evidence layout.

STORY-E2B-004.1:
- Download files via sandbox provider (files.read/API abstraction)
- Collect screenshots, videos, traces (+ logs/results as evidence)
- Save to artifacts/run-<id>/ structure
- Create manifest.json
"""
from __future__ import annotations

import hashlib
import json
import posixpath
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

SCREENSHOT_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv"}
TRACE_EXTS = {".zip"}
TRACE_NAME_HINTS = ("trace", "har")
RESULT_EXTS = {".json"}
LOG_EXTS = {".log", ".txt"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_artifact(path: str) -> str:
    name = posixpath.basename(path).lower()
    ext = posixpath.splitext(name)[1]
    if ext in SCREENSHOT_EXTS or "screenshot" in name:
        return "screenshot"
    if ext in VIDEO_EXTS or "video" in name:
        return "video"
    if ext in TRACE_EXTS or any(h in name for h in TRACE_NAME_HINTS):
        return "trace"
    if "console" in name and ext in (".log", ".txt", ".json"):
        return "console"
    if "network" in name and ext in (".json", ".har", ""):
        return "network"
    if name == "step_results.json" or "result" in name:
        return "result"
    if ext in LOG_EXTS:
        return "log"
    if ext in RESULT_EXTS:
        return "json"
    return "artifact"


@dataclass
class ArtifactRecord:
    type: str
    path: str  # repo/workspace-relative path for compatibility (e.g. artifacts/run-x/file.png)
    filename: str
    remote_path: Optional[str] = None
    size_bytes: int = 0
    sha256: Optional[str] = None
    collected_at: str = field(default_factory=_utc_now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_manifest_entry(self, include_extended: bool = True) -> Dict[str, Any]:
        # Keep legacy-compatible keys first.
        entry: Dict[str, Any] = {"type": self.type, "path": self.path}
        if include_extended:
            entry.update(
                {
                    "filename": self.filename,
                    "remote_path": self.remote_path,
                    "size_bytes": self.size_bytes,
                    "sha256": self.sha256,
                    "collected_at": self.collected_at,
                }
            )
            if self.metadata:
                entry["metadata"] = self.metadata
        return entry


@dataclass
class ArtifactManifest:
    run_id: str
    source: Dict[str, Any] = field(default_factory=dict)
    artifacts: List[ArtifactRecord] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now)
    schema_version: str = "1.0"

    def to_dict(self, include_extended: bool = True) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "source": self.source,
            "artifacts": [a.to_manifest_entry(include_extended=include_extended) for a in self.artifacts],
        }

    def save(self, path: Path, include_extended: bool = True) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(include_extended=include_extended), indent=2), encoding="utf-8")
        return path


class SandboxArtifactCollector:
    """Collects artifacts from a sandbox provider into artifacts/run-<id>/."""

    def __init__(
        self,
        provider: Any,
        sandbox_id: str,
        run_id: str,
        artifacts_root: Path | str = "artifacts",
        include_extended_manifest: bool = True,
    ):
        self.provider = provider
        self.sandbox_id = sandbox_id
        self.run_id = run_id
        self.artifacts_root = Path(artifacts_root)
        self.run_dir = self.artifacts_root / run_id
        self.include_extended_manifest = include_extended_manifest
        self.manifest = ArtifactManifest(
            run_id=run_id,
            source={"provider": type(provider).__name__, "sandbox_id": sandbox_id},
        )

    def collect(
        self,
        remote_paths: Optional[Sequence[str]] = None,
        discover_dirs: Optional[Sequence[str]] = None,
        step_results_path: str = "/home/user/artifacts/step_results.json",
        include_step_result_screenshots: bool = True,
        max_discover: int = 200,
    ) -> ArtifactManifest:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        seen: set[str] = set()
        candidates: List[str] = []

        def add(path: Optional[str]) -> None:
            if not path:
                return
            p = str(path)
            if p not in seen:
                seen.add(p)
                candidates.append(p)

        # Always try common evidence locations.
        for p in (remote_paths or []):
            add(p)
        add(step_results_path)
        add("/home/user/artifacts/trace.zip")
        add("/home/user/artifacts/console.log")
        add("/home/user/artifacts/network.json")
        add("/home/user/screenshot.png")  # legacy

        # Pull screenshot paths from step_results.json if present.
        step_results = self._download_bytes(step_results_path)
        if step_results:
            self._save_local(step_results_path, step_results)
            if include_step_result_screenshots:
                try:
                    parsed = json.loads(step_results.decode("utf-8"))
                    for step in parsed.get("steps", []) or []:
                        add(step.get("screenshot"))
                        for extra in step.get("screenshots") or []:
                            add(extra)
                    for case in parsed.get("cases", []) or []:
                        for step in case.get("steps", []) or []:
                            add(step.get("screenshot"))
                except Exception:
                    pass

        # Best-effort discovery through provider command execution.
        for d in (discover_dirs or ["/home/user/artifacts", "/home/user"]):
            for found in self._discover_remote_files(d, limit=max_discover):
                add(found)

        for remote_path in candidates:
            # step_results may already be saved; still record if desired
            local = self.run_dir / posixpath.basename(remote_path)
            if local.exists() and remote_path == step_results_path and any(a.remote_path == remote_path for a in self.manifest.artifacts):
                continue
            data = self._download_bytes(remote_path)
            if not data:
                continue
            # Avoid overwriting different remote files with same basename: disambiguate.
            target = self._unique_local_path(remote_path)
            target.write_bytes(data)
            rel_path = self._relative_artifact_path(target)
            rec = ArtifactRecord(
                type=classify_artifact(remote_path),
                path=rel_path,
                filename=target.name,
                remote_path=remote_path,
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
            self.manifest.artifacts.append(rec)

        self.manifest.save(self.run_dir / "manifest.json", include_extended=self.include_extended_manifest)
        return self.manifest

    def _download_bytes(self, remote_path: str) -> bytes:
        try:
            data = self.provider.download_file(self.sandbox_id, remote_path)
            if not data:
                return b""
            if isinstance(data, str):
                return data.encode("utf-8", errors="replace")
            return bytes(data)
        except Exception:
            return b""

    def _save_local(self, remote_path: str, data: bytes) -> Optional[Path]:
        if not data:
            return None
        target = self._unique_local_path(remote_path)
        target.write_bytes(data)
        rel_path = self._relative_artifact_path(target)
        self.manifest.artifacts.append(
            ArtifactRecord(
                type=classify_artifact(remote_path),
                path=rel_path,
                filename=target.name,
                remote_path=remote_path,
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
        )
        return target

    def _unique_local_path(self, remote_path: str) -> Path:
        base = posixpath.basename(remote_path) or "artifact.bin"
        target = self.run_dir / base
        if not target.exists():
            return target
        stem = target.stem
        suffix = target.suffix
        parent_hint = posixpath.basename(posixpath.dirname(remote_path)) or "remote"
        candidate = self.run_dir / f"{stem}_{parent_hint}{suffix}"
        i = 2
        while candidate.exists():
            candidate = self.run_dir / f"{stem}_{parent_hint}_{i}{suffix}"
            i += 1
        return candidate

    def _relative_artifact_path(self, target: Path) -> str:
        # Match existing manifest style: artifacts/run-<id>/<file>
        try:
            cwd_rel = target.resolve().relative_to(Path.cwd().resolve())
            return str(cwd_rel).replace("\\", "/")
        except Exception:
            return str(Path(self.artifacts_root.name) / self.run_id / target.name).replace("\\", "/")

    def _discover_remote_files(self, directory: str, limit: int = 200) -> List[str]:
        try:
            cmd = f"find {directory} -maxdepth 4 -type f 2>/dev/null | head -n {int(limit)}"
            res = self.provider.run_command(self.sandbox_id, cmd, timeout=30)
            stdout = (res or {}).get("stdout") or ""
            if not stdout and isinstance(res, dict):
                stdout = str(res.get("output", ""))
            paths = [line.strip() for line in stdout.splitlines() if line.strip().startswith("/")]
            # Prefer evidence-like files
            prioritized = [p for p in paths if classify_artifact(p) in {"screenshot", "video", "trace", "console", "network", "result", "log"}]
            others = [p for p in paths if p not in prioritized]
            return prioritized + others
        except Exception:
            return []


def collect_sandbox_artifacts(
    provider: Any,
    sandbox_id: str,
    run_id: str,
    artifacts_root: Path | str = "artifacts",
    remote_paths: Optional[Sequence[str]] = None,
    discover_dirs: Optional[Sequence[str]] = None,
    include_extended_manifest: bool = True,
) -> ArtifactManifest:
    collector = SandboxArtifactCollector(
        provider=provider,
        sandbox_id=sandbox_id,
        run_id=run_id,
        artifacts_root=artifacts_root,
        include_extended_manifest=include_extended_manifest,
    )
    return collector.collect(remote_paths=remote_paths, discover_dirs=discover_dirs)
