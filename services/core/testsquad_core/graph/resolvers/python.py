from typing import List, Dict, Set, Tuple
import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Node
from testsquad_shared import SymbolType

class PythonResolver:
    def __init__(self):
        try:
            self.language = Language(tspython.language(), "python")
        except TypeError:
            self.language = Language(tspython.language())

        self.parser = Parser()
        try:
            self.parser.set_language(self.language)
        except AttributeError:
            self.parser = Parser(self.language)

    def resolve_relationships(self, file_path: str, content: str) -> Tuple[List[Dict], List[Dict], List[Dict]]:
        """
        Returns (symbols, imports, calls)
        - symbols: list of {name, type, start_line, end_line}
        - imports: list of {target_module, is_from_import}
        - calls: list of {caller_symbol_name, callee_name}
        """
        tree = self.parser.parse(bytes(content, "utf8"))
        symbols = []
        imports = []
        calls = []
        
        self._walk_tree(tree.root_node, content, symbols, imports, calls, current_symbol=None)
        
        return symbols, imports, calls

    def _walk_tree(self, node: Node, content: str, symbols: List[Dict], imports: List[Dict], calls: List[Dict], current_symbol: str = None):
        # 1. Identify Symbols (Functions/Classes)
        new_symbol = current_symbol
        decorators = []
        content_bytes = bytes(content, "utf8")

        # Handle decorated definitions
        target_node = node
        if node.type == "decorated_definition":
            for child in node.children:
                if child.type == "decorator":
                    decorators.append(content_bytes[child.start_byte:child.end_byte].decode("utf8", errors="ignore").strip())
                elif child.type in ["function_definition", "class_definition"]:
                    target_node = child
                    break

        if target_node.type == "function_definition":
            name = self._get_name(target_node, content_bytes)
            if name and self._is_valid_identifier(name):
                symbols.append({
                    "name": name,
                    "type": SymbolType.FUNCTION,
                    "start_line": target_node.start_point[0] + 1,
                    "end_line": target_node.end_point[0] + 1,
                    "decorators": decorators
                })
                new_symbol = name
        elif target_node.type == "class_definition":
            name = self._get_name(target_node, content_bytes)
            if name and self._is_valid_identifier(name):
                symbols.append({
                    "name": name,
                    "type": SymbolType.CLASS,
                    "start_line": target_node.start_point[0] + 1,
                    "end_line": target_node.end_point[0] + 1,
                    "decorators": decorators
                })
                new_symbol = name

        # 2. Identify Imports
        if target_node.type == "import_statement":
            # import math, os
            for child in target_node.children:
                if child.type == "dotted_name":
                    imports.append({
                        "target": content_bytes[child.start_byte:child.end_byte].decode("utf8", errors="ignore"), 
                        "type": "import",
                        "line": child.start_point[0],
                        "character": child.start_point[1]
                    })
        elif target_node.type == "import_from_statement":
            # from os import path
            module_node = None
            for child in target_node.children:
                if child.type == "dotted_name" or child.type == "relative_import":
                    module_node = child
                    break
            if module_node:
                imports.append({
                    "target": content_bytes[module_node.start_byte:module_node.end_byte].decode("utf8", errors="ignore"), 
                    "type": "from_import",
                    "line": module_node.start_point[0],
                    "character": module_node.start_point[1]
                })

        if target_node.type == "call" and current_symbol:
            # function_name(...)
            func_node = target_node.child_by_field_name("function")
            if func_node:
                call_name = content_bytes[func_node.start_byte:func_node.end_byte].decode("utf8", errors="ignore")
                calls.append({
                    "caller": current_symbol, 
                    "callee": call_name,
                    "line": func_node.start_point[0],
                    "character": func_node.start_point[1]
                })

        # Recurse
        for child in target_node.children:
            self._walk_tree(child, content, symbols, imports, calls, new_symbol)

    def _get_name(self, node: Node, content_bytes: bytes) -> str:
        for child in node.children:
            if child.type == "identifier":
                return content_bytes[child.start_byte:child.end_byte].decode("utf8", errors="ignore")
        return ""

    def _is_valid_identifier(self, name: str) -> bool:
        """Strict check for valid symbol names to avoid noise (Skip internal/private)."""
        import re
        if not name or len(name) < 3:
            return False
        
        # Skip private methods and dunder methods
        if name.startswith("_"):
            return False
            
        # Common noisy names in Python
        blacklist = {"data", "info", "config", "params", "result"}
        if name.lower() in blacklist:
            return False
            
        return bool(re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', name))
