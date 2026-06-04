import re
import logging
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)


class SymbolSummarizer:
    """Extract natural language summaries from code symbols without LLM.
    
    Extracts:
    - Docstrings (Python triple-quoted, JS/TS JSDoc)
    - Adjacent comments
    - Function signatures
    - Test descriptions
    """

    def summarize_product(self, file_content: str, symbol: Dict) -> str:
        """Extract summary for a product symbol (function/class)."""
        name = symbol.get("name", "")
        sym_type = symbol.get("type", "function")
        start_line = symbol.get("start_line", 1)
        
        lines = file_content.split("\n")
        if start_line > len(lines):
            return self._fallback_summary(name, sym_type)
        
        docstring = self._extract_docstring(lines, start_line)
        comments = self._extract_comments(lines, start_line)
        signature = self._build_signature(symbol, file_content)
        
        parts = []
        if docstring:
            parts.append(docstring)
        if comments:
            parts.append(comments)
        if signature:
            parts.append("Signature: " + signature)
        
        if not parts:
            return self._fallback_summary(name, sym_type)
        
        return " ".join(parts)

    def summarize_test(self, file_content: str, test_symbol: Dict) -> str:
        """Extract summary for a test symbol."""
        name = test_symbol.get("name", "")
        start_line = test_symbol.get("start_line", 1)
        
        lines = file_content.split("\n")
        if start_line > len(lines):
            return self._fallback_test_summary(name)
        
        description = self._parse_test_description(name, lines, start_line)
        fixtures = self._extract_fixtures(lines, start_line)
        docstring = self._extract_docstring(lines, start_line)
        
        parts = []
        if description:
            parts.append("Tests " + description)
        if fixtures:
            parts.append("Setup: " + fixtures)
        if docstring:
            parts.append(docstring)
        
        if not parts:
            return self._fallback_test_summary(name)
        
        return ". ".join(parts)

    def _extract_docstring(self, lines: List[str], start_line: int) -> Optional[str]:
        """Extract docstring from symbol definition."""
        line_idx = start_line - 1
        if line_idx >= len(lines):
            return None
        
        line = lines[line_idx].strip()
        
        # Check 5 lines before and after for any docstring pattern
        for offset in range(-5, 6):
            check_idx = line_idx + offset
            if check_idx < 0 or check_idx >= len(lines):
                continue
            
            check_line = lines[check_idx].strip()
            
            # Python triple-quoted """
            if check_line.startswith('"""') and check_line.endswith('"""'):
                doc = check_line[3:-3].strip()
                if doc:
                    return doc
            
            # Python single-quoted '''
            if check_line.startswith("'''") and check_line.endswith("'" * 3):
                doc = check_line[3:-3].strip()
                if doc:
                    return doc
            
            # JS/TS single-line JSDoc: /** ... */
            if check_line.startswith("/**") and check_line.endswith("*/"):
                jsdoc = check_line[3:-2].strip()
                if jsdoc:
                    return jsdoc
            
            # Multi-line start (/** without */)
            if check_line.startswith("/**") and "*/" not in check_line:
                result = [check_line[3:].strip()]
                for i in range(check_idx + 1, min(check_idx + 10, len(lines))):
                    next_line = lines[i].strip()
                    if "*/" in next_line:
                        close_idx = next_line.find("*/")
                        if close_idx >= 0:
                            result.append(next_line[:close_idx].strip())
                        break
                    else:
                        result.append(next_line)
                jsdoc = " ".join(result).strip()
                if jsdoc:
                    return jsdoc
            
            # Python multi-line start (""" without closing)
            if check_line.startswith('"""') and '"""' not in check_line[3:]:
                result = [check_line[3:].strip()]
                for i in range(check_idx + 1, min(check_idx + 10, len(lines))):
                    next_line = lines[i].strip()
                    if '"""' in next_line:
                        result.append(next_line.split('"""')[0].strip())
                        break
                    else:
                        result.append(next_line)
                doc = " ".join(result).strip()
                if doc:
                    return doc
        
        return None

    def _extract_comments(self, lines: List[str], start_line: int) -> Optional[str]:
        """Extract adjacent comments."""
        comments = []
        line_idx = start_line - 1
        
        start_check = max(0, line_idx - 3)
        
        for i in range(start_check, line_idx):
            if i >= len(lines):
                continue
            line = lines[i].strip()
            if line.startswith("#") or line.startswith("//"):
                comment = line.lstrip("#/").strip()
                if comment and not comment.startswith("@"):
                    comments.append(comment)
        
        return " ".join(comments[:2]) if comments else None

    def _build_signature(self, symbol: Dict, file_content: str) -> str:
        """Build function signature."""
        name = symbol.get("name", "")
        sym_type = symbol.get("type", "function")
        
        if sym_type == "class":
            return "class " + name
        
        params = symbol.get("parameters", [])
        if params:
            param_str = ", ".join(
                p.get("name", "arg") + ": " + p.get("type", "any")
                for p in params
            )
            return_type = symbol.get("return_type", "any")
            return name + "(" + param_str + ") -> " + return_type
        
        return name + "(...)"

    def _parse_test_description(self, name: str, lines: List[str], start_line: int) -> Optional[str]:
        """Parse test description."""
        if name.startswith("test_"):
            return name[5:].replace("_", " ")
        
        line_idx = start_line - 1
        start_check = max(0, line_idx - 2)
        end_check = min(len(lines), line_idx + 3)
        
        for i in range(start_check, end_check):
            line = lines[i] if i < len(lines) else ""
            match = re.search(r"(?:it|test)\s*\(\s*['\"]([^'\"]+)['\"]", line)
            if match:
                return match.group(1)
        
        return None

    def _extract_fixtures(self, lines: List[str], start_line: int) -> Optional[str]:
        """Extract setup patterns."""
        fixtures = []
        line_idx = start_line - 1
        start_check = max(0, line_idx - 10)
        
        for i in range(start_check, line_idx):
            if i >= len(lines):
                continue
            line = lines[i].strip()
            for pattern in ["beforeEach", "beforeAll", "setUp", "describe(", "context("]:
                if pattern in line:
                    fixtures.append(pattern.rstrip("("))
        
        return ", ".join(fixtures[:2]) if fixtures else None

    def _fallback_summary(self, name: str, sym_type: str) -> str:
        """Graceful degradation."""
        return ("class " + name) if sym_type == "class" else "function " + name

    def _fallback_test_summary(self, name: str) -> str:
        """Graceful degradation for tests."""
        return ("Tests " + name[5:].replace("_", " ")) if name.startswith("test_") else "Test " + name