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
            # import pkg.mod as pm, other
            for child in target_node.children:
                if child.type == "dotted_name":
                    module = self._text(child, content_bytes)
                    imports.append({
                        "target": module,
                        "type": "import",
                        "module": module,
                        "alias": None,
                        "line": child.start_point[0],
                        "character": child.start_point[1]
                    })
                elif child.type == "aliased_import":
                    name_node = child.child_by_field_name("name")
                    alias_node = child.child_by_field_name("alias")
                    module = self._text(name_node, content_bytes) if name_node else ""
                    alias = self._text(alias_node, content_bytes) if alias_node else None
                    imports.append({
                        "target": module,
                        "type": "import",
                        "module": module,
                        "alias": alias,
                        "line": child.start_point[0],
                        "character": child.start_point[1]
                    })
        elif target_node.type == "import_from_statement":
            # from pkg.sub import a, b as c
            # from . import sibling
            # from ..pkg import thing
            module_node = target_node.child_by_field_name("module_name")
            module = ""
            level = 0
            if module_node is not None:
                if module_node.type == "relative_import":
                    for part in module_node.children:
                        if part.type == "import_prefix":
                            level = self._text(part, content_bytes).count(".")
                        elif part.type == "dotted_name":
                            module = self._text(part, content_bytes)
                else:
                    module = self._text(module_node, content_bytes)

            names = []
            for idx, child in enumerate(target_node.children):
                if child is module_node:
                    continue
                field = target_node.field_name_for_child(idx)
                if child.type == "dotted_name" and field == "name":
                    names.append([self._text(child, content_bytes), None])
                elif child.type == "aliased_import" and field == "name":
                    name_node = child.child_by_field_name("name")
                    alias_node = child.child_by_field_name("alias")
                    names.append([
                        self._text(name_node, content_bytes) if name_node else "",
                        self._text(alias_node, content_bytes) if alias_node else None,
                    ])
                elif child.type == "wildcard_import":
                    names.append(["*", None])

            imports.append({
                "target": ("." * level) + module,
                "type": "from_import",
                "module": module,
                "level": level,
                "names": names,
                "line": module_node.start_point[0] if module_node else target_node.start_point[0],
                "character": module_node.start_point[1] if module_node else target_node.start_point[1]
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

    def _text(self, node: Node, content_bytes: bytes) -> str:
        return content_bytes[node.start_byte:node.end_byte].decode("utf8", errors="ignore")

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
