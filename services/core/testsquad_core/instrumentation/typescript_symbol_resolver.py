import os
import logging
from typing import Dict, List, Optional, Set
from dataclasses import dataclass

from tree_sitter import Language, Parser, Node
import tree_sitter_typescript as tspy
import tree_sitter_javascript as tsjs
import tree_sitter_python as tspython

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
                cls._languages[lang] = Language(tspy.language_typescript(), "typescript")
            elif lang == "tsx":
                cls._languages[lang] = Language(tspy.language_tsx(), "tsx")
            else:
                cls._languages[lang] = Language(tsjs.language(), "javascript")
            parser = Parser()
            parser.set_language(cls._languages[lang])
            cls._parsers[lang] = parser
        return cls._parsers[lang]

    def __init__(self):
        self._cache: Dict[str, List[Symbol]] = {}

    @staticmethod
    def _detect_language(file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower().lstrip(".")
        return {"ts": "typescript", "tsx": "tsx", "js": "javascript", "jsx": "javascript"}.get(ext, "javascript")

    def resolve_symbols(self, file_path: str, covered_lines: Dict[str, List[int]]) -> List[Symbol]:
        all_lines: Set[int] = set()
        for lines in covered_lines.values():
            all_lines.update(lines)

        if not all_lines:
            return []

        symbols = self._get_symbols(file_path)

        result = []
        for sym in symbols:
            symbol_lines = set(range(sym.start_line, sym.end_line + 1))
            if symbol_lines & all_lines:
                result.append(sym)

        return result

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
