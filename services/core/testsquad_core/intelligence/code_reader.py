import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)


class CodeReader:
    """Read actual source code from disk using Neo4j node metadata.

    For symbols: uses file_path + start_line/end_line (exact line range).
    For tests: uses file_path + function name search (no line numbers available).
    """

    def __init__(self, base_dirs: list = None):
        self._base_dirs = base_dirs or []

    def _resolve(self, file_path: str) -> str:
        """Resolve file path, trying relative against known base dirs."""
        if os.path.exists(file_path):
            return file_path
        for base in self._base_dirs:
            candidate = os.path.join(base, file_path)
            if os.path.exists(candidate):
                return candidate
        return file_path

    def read_symbol(
        self, file_path: str, start_line: int, end_line: int
    ) -> str:
        """Read symbol source code from disk by line range."""
        return self._read_lines(file_path, start_line, end_line)

    def read_test(self, file_path: str, test_name: str) -> str:
        """Read test function code from disk by name search.

        Handles name formats:
        - "compound" (simple function name)
        - "test_compound.py::test_compound" (file::function)
        - "test_store.py::TestStore::test_get" (file::class::function)
        - "test_store.py::test_get[param]" (file::function[param])
        """
        func_name = self._parse_function_name(test_name)
        if not func_name:
            return ""

        return self._extract_function(file_path, func_name)

    def _parse_function_name(self, test_name: str) -> str:
        """Extract base function name from qualified test name."""
        parts = test_name.split("::")
        # Last part is the function name, may have [parametrize] suffix
        func_part = parts[-1]
        return func_part.split("[")[0] if "[" in func_part else func_part

    def _extract_function(self, file_path: str, func_name: str) -> str:
        """Extract function body from file by function name."""
        resolved = self._resolve(file_path)
        if not os.path.exists(resolved):
            logger.warning(f"File not found: {file_path} (resolved: {resolved})")
            return f"def {func_name}(...):  # file not found"
        try:
            with open(resolved) as f:
                content = f.read()
        except Exception as e:
            logger.warning(f"Error reading {resolved}: {e}")
            return f"def {func_name}(...):  # read error"

        pattern = rf"^[ \t]*(async\s+)?def {func_name}\b"
        match = re.search(pattern, content, re.MULTILINE)
        if not match:
            return f"def {func_name}(...):  # not found in file"

        start = match.start()
        rest = content[start:]
        next_def = re.search(r"\n[ \t]*(async\s+)?def |\n[ \t]*class |\Z", rest)
        end = start + (next_def.start() + 1 if next_def else len(rest))

        return content[start:end].rstrip("\n")

    def _read_lines(
        self, file_path: str, start_line: int, end_line: int
    ) -> str:
        """Read specific line range from file."""
        resolved = self._resolve(file_path)
        if not os.path.exists(resolved):
            logger.warning(f"File not found: {file_path} (resolved: {resolved})")
            return f"# file not found: {os.path.basename(file_path)}"
        try:
            with open(resolved) as f:
                lines = f.readlines()
        except Exception as e:
            logger.warning(f"Error reading {resolved}: {e}")
            return f"# read error: {e}"

        # start_line/end_line are 1-indexed
        code = "".join(lines[start_line - 1 : end_line])
        return code.rstrip("\n")
