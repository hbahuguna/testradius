"""File tools — external integration exposed via MCP (hybrid pattern).

file_read / file_save touch the filesystem and are therefore marked
`external=True`: the agent can still call them directly through the registry,
but in the hybrid model they are the ones surfaced as MCP tools so an
external orchestrator controls file access boundaries.
"""

from __future__ import annotations

from pathlib import Path


def file_read(path: str) -> str:
    """Read a file from disk and return its contents."""
    p = Path(path)
    if not p.exists():
        return f"[file_read error: {path} does not exist]"
    try:
        return p.read_text(encoding="utf-8")
    except OSError as e:
        return f"[file_read error: {e}]"


def file_save(path: str, content: str) -> str:
    """Write content to a file, creating parent directories as needed."""
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Saved {len(content)} bytes to {path}"
    except OSError as e:
        return f"[file_save error: {e}]"
