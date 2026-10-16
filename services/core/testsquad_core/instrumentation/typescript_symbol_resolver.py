import os
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

from tree_sitter import Language, Parser, Node
import tree_sitter_typescript as tspy
import tree_sitter_javascript as tsjs
import tree_sitter_python as tspython

try:  # package import (normal)
    from .attribution import select_innermost_owners
except ImportError:  # pragma: no cover - loaded as a standalone module by path
    import importlib.util as _importlib_util

    _attribution_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "attribution.py"
    )
    _attribution_spec = _importlib_util.spec_from_file_location(
        "_instrumentation_attribution", _attribution_path
    )
    _attribution_mod = _importlib_util.module_from_spec(_attribution_spec)
    _attribution_spec.loader.exec_module(_attribution_mod)
    select_innermost_owners = _attribution_mod.select_innermost_owners

logger = logging.getLogger(__name__)


@dataclass
class Symbol:
    name: str
    symbol_type: str
    file_path: str
    start_line: int
    end_line: int
    full_signature: Optional[str] = None


class TypeScriptSymbolResolver:
    _parsers: Dict[str, Parser] = {}
    _languages: Dict[str, Language] = {}

    @classmethod
    def _get_parser(cls, lang: str) -> Parser:
        if lang not in cls._parsers:
            if lang == "typescript":
                pointer = tspy.language_typescript()
            elif lang == "tsx":
                pointer = tspy.language_tsx()
            else:
                pointer = tsjs.language()
            try:
                # tree-sitter < 0.22 accepted (pointer, name)
                cls._languages[lang] = Language(pointer, lang)
            except TypeError:
                # tree-sitter >= 0.22 takes only the pointer
                cls._languages[lang] = Language(pointer)
            try:
                parser = Parser()
                parser.set_language(cls._languages[lang])
            except AttributeError:
                # tree-sitter >= 0.25 removed Parser.set_language
                parser = Parser(cls._languages[lang])
            cls._parsers[lang] = parser
        return cls._parsers[lang]

    def __init__(self):
        self._cache: Dict[str, List[Symbol]] = {}

    @staticmethod
    def _detect_language(file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower().lstrip(".")
        return {"ts": "typescript", "tsx": "tsx", "js": "javascript", "jsx": "javascript"}.get(ext, "javascript")

    def resolve_symbols(self, file_path: str, covered_lines: Dict[str, List[int]]) -> List[Symbol]:
        """Attribute covered lines to symbols, innermost enclosing symbol wins.

        Mirrors Python's ``SymbolResolver`` (via the shared
        ``select_innermost_owners`` helper): a line inside a method credits the
        method only, never its enclosing class.
        """
        return select_innermost_owners(self._get_symbols(file_path), covered_lines)

    def _get_symbols(self, file_path: str) -> List[Symbol]:
        if file_path in self._cache:
            return self._cache[file_path]

        if not os.path.exists(file_path):
            return []

        lang = self._detect_language(file_path)
        symbols = []
        try:
            parser = self._get_parser(lang)
            with open(file_path, "rb") as f:
                content = f.read()
            tree = parser.parse(content)
            self._collect_symbols(tree.root_node, file_path, symbols, content)
        except Exception as e:
            logger.warning(f"Failed to parse symbols from {file_path}: {e}")

        self._cache[file_path] = symbols
        return symbols

    def _collect_symbols(self, node: Node, file_path: str, symbols: List[Symbol], content: bytes, visited: set = None):
        if visited is None:
            visited = set()
        node_id = id(node)
        if node_id in visited:
            return
        visited.add(node_id)

        if node.type == "function_declaration":
            name = self._child_text(node, "name", content)
            if name:
                start = node.start_point[0] + 1
                end = node.end_point[0] + 1
                symbols.append(Symbol(name=name, symbol_type="function", file_path=file_path, start_line=start, end_line=end))

        elif node.type == "method_definition":
            name = self._child_text(node, "name", content)
            if name:
                start = node.start_point[0] + 1
                end = node.end_point[0] + 1
                symbols.append(Symbol(name=name, symbol_type="method", file_path=file_path, start_line=start, end_line=end))

        elif node.type == "class_declaration":
            name = self._child_text(node, "name", content)
            if name:
                start = node.start_point[0] + 1
                end = node.end_point[0] + 1
                symbols.append(Symbol(name=name, symbol_type="class", file_path=file_path, start_line=start, end_line=end))

        elif node.type == "variable_declarator":
            value_node = node.child_by_field_name("value")
            if value_node and value_node.type in ("arrow_function", "function_expression"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._node_text(name_node, content)
                    if name:
                        start = node.start_point[0] + 1
                        end = node.end_point[0] + 1
                        symbols.append(Symbol(name=name, symbol_type="function", file_path=file_path, start_line=start, end_line=end))

        for child in node.children:
            self._collect_symbols(child, file_path, symbols, content, visited)

    @staticmethod
    def _child_text(node: Node, field_name: str, content: bytes) -> Optional[str]:
        child = node.child_by_field_name(field_name)
        if child:
            return content[child.start_byte:child.end_byte].decode("utf-8", errors="ignore")
        return None

    @staticmethod
    def _node_text(node: Node, content: bytes) -> str:
        return content[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")

    def get_symbols(self, file_path: str) -> List[Symbol]:
        return self._get_symbols(file_path)

    def clear_cache(self):
        self._cache.clear()
