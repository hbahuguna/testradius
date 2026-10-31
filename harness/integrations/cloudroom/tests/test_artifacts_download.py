"""Tests for artifact downloader."""
import os
from pathlib import Path
from harness.integrations.cloudroom import CloudRoomClient, ArtifactDownloader


def test_downloader(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDROOM_TOKEN", "test-token")
    client = CloudRoomClient()
    def mock_list_artifacts(session_id):
        return {"files": ["a.png", "b.webm"]}
    def mock_download_artifact(session_id, path):
        return b"data"
    client.list_artifacts = mock_list_artifacts
    client.download_artifact = mock_download_artifact
    dl = ArtifactDownloader(client)
    res = dl.download_all("cr_1", tmp_path)
    assert res["count"] == 2
    assert (tmp_path / "a.png").exists()
