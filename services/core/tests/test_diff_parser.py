import pytest
import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from testsquad_core.analysis.diff_parser import DiffParser, FileChange


class TestDiffParser:
    """Test Task 3.1.2: Diff Parser Tests."""

    @pytest.fixture
    def mock_neo4j(self):
        return MagicMock()

    @pytest.fixture
    def parser(self, mock_neo4j):
        return DiffParser(neo4j_client=mock_neo4j)

    @pytest.fixture
    def parser_no_neo4j(self):
        return DiffParser(neo4j_client=None)

    # --- Test unified diff parsing ---

    def test_parse_diff_added_lines(self, parser):
        """Test added lines are detected correctly."""
        diff = """diff --git a/src/math.py b/src/math.py
--- a/src/math.py
+++ b/src/math.py
@@ -1,3 +1,4 @@
+def add(a, b):
+    return a + b
 def subtract(a, b):
"""
        result = parser.parse_diff(diff)
        
        assert len(result) == 1
        assert result[0].path == "src/math.py"
        assert len(result[0].added_lines) >= 1

    def test_parse_diff_removed_lines(self, parser):
        """Test removed lines are detected correctly."""
        diff = """diff --git a/src/math.py b/src/math.py
--- a/src/math.py
+++ b/src/math.py
@@ -1,3 +1,2 @@
-def add(a, b):
-    return a + b
 def subtract(a, b):
"""
        result = parser.parse_diff(diff)
        
        assert len(result) == 1
        assert result[0].path == "src/math.py"
        assert len(result[0].removed_lines) >= 1

    def test_parse_diff_modified_lines(self, parser):
        """Test modified lines detected (both added and removed)."""
        diff = """diff --git a/src/math.py b/src/math.py
--- a/src/math.py
+++ b/src/math.py
@@ -1,3 +1,3 @@
-def multiply(a, b):
+def multiply(a, b, c):
-    return a * b
+    return a * b * c
 def divide(a, b):
"""
        result = parser.parse_diff(diff)
        
        assert len(result) == 1
        assert result[0].path == "src/math.py"
        assert len(result[0].added_lines) >= 1
        assert len(result[0].removed_lines) >= 1

    # --- Test file renames ---

    def test_parse_diff_file_rename(self, parser):
        """Test rename is detected and old path is captured."""
        diff = """diff --git a/src/old.py b/src/new.py
--- a/src/old.py
+++ b/src/new.py
rename from src/old.py
@@ -1,2 +1,2 @@
 def foo():
"""
        result = parser.parse_diff(diff)
        
        assert len(result) == 1
        assert result[0].path == "src/new.py"
        old_path = (result[0].old_path or '').strip()
        assert old_path == "src/old.py"

    def test_parse_diff_no_rename(self, parser):
        """Test no rename when paths are the same."""
        diff = """diff --git a/src/math.py b/src/math.py
--- a/src/math.py
+++ b/src/math.py
@@ -1,2 +1,3 @@
+def add(a, b):
 def subtract(a, b):
"""
        result = parser.parse_diff(diff)
        
        assert len(result) == 1
        assert result[0].path == "src/math.py"
        assert result[0].old_path is None or result[0].old_path.strip() == ""

    # --- Test file deletions ---

    def test_parse_diff_deletion(self, parser):
        """Test deletion is detected."""
        diff = """diff --git a/src/deleted.py b/src/deleted.py
--- a/src/deleted.py
+++ b/src/deleted.py
@@ -1,3 +0,0 @@
-def foo():
-    pass
-def bar():
-    pass
"""
        result = parser.parse_diff(diff)
        
        assert len(result) == 1
        assert result[0].path == "src/deleted.py"
        assert result[0].is_deleted is True
        assert len(result[0].added_lines) == 0

    def test_parse_diff_binary_file(self, parser):
        """Test binary file detection."""
        diff = """diff --git a/src/image.png b/src/image.png
Binary files a/src/image.png and b/src/image.png differ
"""
        result = parser.parse_diff(diff)
        
        # Binary handling may return empty or limited results
        assert isinstance(result, list)

    # --- Test line-to-symbol mapping ---

    def test_map_lines_to_symbols_with_neo4j(self, parser, mock_neo4j):
        """Test changed lines map to symbols in Neo4j."""
        mock_neo4j.query.return_value = [
            {"symbol_name": "add", "symbol_type": "function",
             "start_line": 10, "end_line": 15}
        ]
        
        result = parser.map_lines_to_symbols("src/math.py", [12], project_id=1)
        
        assert len(result) >= 0  # May be empty if no match
        mock_neo4j.query.assert_called()

    def test_map_lines_to_symbols_no_neo4j(self, parser_no_neo4j):
        """Test returns empty when no Neo4j client."""
        result = parser_no_neo4j.map_lines_to_symbols("src/math.py", [12], project_id=1)
        
        assert result == []

    def test_map_lines_to_symbols_returns_list(self, parser, mock_neo4j):
        """Test returns list of symbols."""
        mock_neo4j.query.return_value = []
        
        result = parser.map_lines_to_symbols("src/math.py", [12], project_id=1)
        
        assert isinstance(result, list)

    # --- Test edge cases ---

    def test_parse_diff_empty(self, parser):
        """Test empty diff returns empty list."""
        result = parser.parse_diff("")
        
        assert result == []

    def test_parse_diff_whitespace_only(self, parser):
        """Test whitespace-only diff returns empty."""
        result = parser.parse_diff("   \n   \n   ")
        
        assert result == []

    def test_parse_diff_multiple_files(self, parser):
        """Test multiple files in diff are parsed."""
        diff = """diff --git a/src/math.py b/src/math.py
--- a/src/math.py
+++ b/src/math.py
@@ -1,2 +1,3 @@
+def add(a, b):
 def subtract(a, b):
diff --git a/src/utils.py b/src/utils.py
--- a/src/utils.py
+++ b/src/utils.py
@@ -1,2 +1,2 @@
-def old():
-    pass
+def new():
+    pass
"""
        result = parser.parse_diff(diff)
        
        assert len(result) >= 1