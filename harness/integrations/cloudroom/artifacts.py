"""Artifact download utilities for Cloud Room."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .client import CloudRoomClient


class ArtifactDownloader:
    """Download artifacts from Cloud Room sandbox."""

    def __init__(self, client: CloudRoomClient):
        self.client = client

    def download_all(self, session_id: str, dest_dir: Path) -> Dict[str, Any]:
        """Download all artifacts from session."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        downloaded = []
        try:
            resp = self.client.list_artifacts(session_id)
            files = resp.get("files", []) or resp.get("artifacts", [])
            for f in files:
                fname = f if isinstance(f, str) else f.get("name") or f.get("path", "")
                if not fname or fname in (".", ".."):
                    continue
                try:
                    content = self.client.download_artifact(session_id, fname)
                    out_path = dest_dir / Path(fname).name
                    out_path.write_bytes(content)
                    downloaded.append(str(out_path))
                except Exception:
                    continue
        except Exception:
            pass
        return {"downloaded": downloaded, "count": len(downloaded)}
