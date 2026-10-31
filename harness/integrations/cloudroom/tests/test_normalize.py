"""Tests for evidence normalization."""
import os
from pathlib import Path
from harness.integrations.cloudroom import EvidenceNormalizer


def test_normalize(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "screen1.png").write_bytes(b"png")
    (src / "video.webm").write_bytes(b"webm")
    (src / "trace.json").write_text("{}")
    
    norm = EvidenceNormalizer()
    res = norm.normalize(src, "123", tmp_path)
    assert len(res["screenshots"]) == 1
    assert res["video"] is not None
    assert len(res["traces"]) == 1
    assert (tmp_path / "run-123" / "manifest.json").exists()
