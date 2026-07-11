"""Knowledge tools: surface repo context (Page Objects, test patterns) to the agent.

These tools query the PageObjectStore and RepoScanner (Layer 4) and provide
formatted output for the agent's prompt, enabling it to generate more
idiomatic and context-aware tests.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..knowledge.page_object_store import PageObjectStore
from ..knowledge.repo_scanner import RepoScanner

# Assuming the agent is run from the project root or the worktree root.
# The actual `artifacts` folder is at the top-level of the repository.
_GLOBAL_REPO_ROOT = Path(os.environ.get("SDET_REPO_ROOT", Path(__file__).parents[4])) # parents[4] for sdet-agent/sdet_agent/tools/knowledge_tools.py -> worktree root
_page_object_store: PageObjectStore | None = None
_repo_scanner: RepoScanner | None = None

def _get_po_store() -> PageObjectStore:
    global _page_object_store
    if _page_object_store is None:
        _page_object_store = PageObjectStore(repo_root=_GLOBAL_REPO_ROOT)
    return _page_object_store

def _get_repo_scanner() -> RepoScanner:
    global _repo_scanner
    if _repo_scanner is None:
        _repo_scanner = RepoScanner(repo_root=_GLOBAL_REPO_ROOT)
    return _repo_scanner


def knowledge_list_page_objects() -> str:
    """List all discovered Page Objects with their locators and methods."""
    store = _get_po_store()
    return store.to_formatted_string()


def knowledge_list_repo_patterns() -> str:
    """List common test patterns and utility functions found in the repo."""
    scanner = _get_repo_scanner()
    return scanner.to_formatted_string()
