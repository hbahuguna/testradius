"""Repo Scanner: discovers common test patterns and utility functions.

Scans `artifacts/e2e-tests/` for existing test files (`.spec.ts`)
and utility files (e.g., `utils/*.ts`). Extracts common imports, test
structures (describe, beforeEach), and utility function definitions.
This helps the agent generate idiomatic code (textbook Ch.1 Layer 4).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("sdet_agent.knowledge.repo_scanner")


@dataclass
class UtilityFunctionInfo:
    name: str
    file_path: Path
    signature: str
    source_code: str

@dataclass
class TestFileSummary:
    file_path: Path
    describes: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)


class RepoScanner:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.e2e_tests_dir = repo_root / "artifacts" / "e2e-tests"
        self._utilities: dict[str, UtilityFunctionInfo] = {}
        self._test_summaries: list[TestFileSummary] = []
        self.load_repo_patterns()

    def load_repo_patterns(self) -> None:
        if not self.e2e_tests_dir.exists():
            logger.warning("E2E Tests directory not found: %s", self.e2e_tests_dir)
            return
        
        # Scan for utility files (e.g., in `utils/` or direct `e2e-tests/`) 
        # This part requires more specific knowledge about common utility locations. 
        # For now, a simplified scan for function exports.
        for ts_file in self.e2e_tests_dir.glob("**/*.ts"):
            if "pages" in ts_file.parts: # Skip page objects (handled by PageObjectStore)
                continue
            try:
                content = ts_file.read_text(encoding="utf-8")
                self._parse_utilities(ts_file, content)
                self._parse_test_file(ts_file, content)
            except Exception as exc: # noqa: BLE001
                logger.error("Error parsing repo file %s: %s", ts_file, exc)
        logger.info("Loaded %d utility functions and %d test summaries", len(self._utilities), len(self._test_summaries))

    def _parse_utilities(self, file_path: Path, content: str) -> None:
        # Regex for exported functions
        for match in re.finditer(r"export (async\s+)?function (\w+)\(([^)]*)\)(\s*:\s*\w+)?\s*{[^}]*?}", content, re.DOTALL):
            func_name = match.group(2)
            func_args = match.group(3)
            self._utilities[func_name] = UtilityFunctionInfo(
                name=func_name, 
                file_path=file_path, 
                signature=f"{func_name}({func_args})",
                source_code=match.group(0),
            )

    def _parse_test_file(self, file_path: Path, content: str) -> None:
        if not file_path.name.endswith(".spec.ts"):
            return
        summary = TestFileSummary(file_path=file_path)

        # Imports
        summary.imports = re.findall(r"import .* from ['\"](.*)['\"];", content)

        # describe blocks
        summary.describes = re.findall(r"test\.describe\(['\"](.*)['\"]", content)

        # test blocks
        summary.tests = re.findall(r"test\(['\"](.*)['\"]", content)
        self._test_summaries.append(summary)

    def get_utility(self, name: str) -> Optional[UtilityFunctionInfo]:
        return self._utilities.get(name)

    def list_utilities(self) -> list[UtilityFunctionInfo]:
        return list(self._utilities.values())

    def list_test_summaries(self) -> list[TestFileSummary]:
        return list(self._test_summaries)

    def to_formatted_string(self) -> str:
        if not self._utilities and not self._test_summaries:
            return "No repo patterns loaded."
        parts: list[str] = ["=== Available Repo Patterns ==="]
        if self._utilities:
            parts.append("\n--- Utility Functions ---")
            for util in self._utilities.values():
                parts.append(f"File: {util.file_path.relative_to(self.repo_root)}")
                parts.append(f"  Function: {util.signature}")
        if self._test_summaries:
            parts.append("\n--- Test File Summaries ---")
            for ts in self._test_summaries:
                parts.append(f"File: {ts.file_path.relative_to(self.repo_root)}")
                parts.append(f"  Describes: {', '.join(ts.describes)}")
                parts.append(f"  Tests: {len(ts.tests)} tests")
        return "\n".join(parts)
