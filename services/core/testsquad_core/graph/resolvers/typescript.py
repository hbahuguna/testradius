from typing import List, Dict, Tuple
import tree_sitter_typescript as ts
import tree_sitter_javascript as js
from tree_sitter import Language, Parser, Node
from testsquad_shared import SymbolType

class TypescriptResolver:
    def __init__(self, use_typescript: bool = True):
        try:
            if use_typescript:
                self.language = Language(ts.language_typescript(), "typescript")
            else:
                self.language = Language(js.language(), "javascript")
            if use_typescript:
                self.tsx_language = Language(ts.language_tsx(), "tsx")
        except TypeError:
            # Handle tree-sitter 0.22+ where name argument is removed
            if use_typescript:
                self.language = Language(ts.language_typescript())
            else:
                self.language = Language(js.language())
            if use_typescript:
                self.tsx_language = Language(ts.language_tsx())

        self.parser = Parser()
        try:
            self.parser.set_language(self.language)
        except AttributeError:
            # Handle tree-sitter 0.22+ where set_language is removed or constructor used
            self.parser = Parser(self.language)

    def resolve_relationships(self, file_path: str, content: str) -> Tuple[List[Dict], List[Dict], List[Dict]]:
        """
        Returns (symbols, imports, calls)
        - symbols: list of {name, type, start_line, end_line}
        - imports: list of {target_module, is_from_import}
        - calls: list of {caller_symbol_name, callee_name}
        """
        content_bytes = bytes(content, "utf8")
        tree = self.parser.parse(content_bytes)
        symbols = []
        imports = []
        calls = []
        
        self._walk_tree(tree.root_node, content_bytes, symbols, imports, calls, current_symbol=None)
        
        return symbols, imports, calls

    def _walk_tree(self, node: Node, content_bytes: bytes, symbols: List[Dict], imports: List[Dict], calls: List[Dict], current_symbol: str = None):
        new_symbol = current_symbol
        
        # 1. Identify Symbols (Functions, Classes, Methods)
        if node.type in ["function_declaration", "method_definition", "function_signature"]:
            name = self._get_name(node, content_bytes)
            if name and self._is_valid_identifier(name):
                symbols.append({
                    "name": name,
                    "type": SymbolType.FUNCTION,
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "decorators": []
                })
                new_symbol = name
        elif node.type == "class_declaration":
            name = self._get_name(node, content_bytes)
            if name and self._is_valid_identifier(name):
                symbols.append({
                    "name": name,
                    "type": SymbolType.CLASS,
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "decorators": []
                })
                new_symbol = name
        elif node.type == "variable_declarator":
            name_node = node.child_by_field_name("name")
            value_node = node.child_by_field_name("value")
            if name_node and value_node and value_node.type in ["arrow_function", "function_expression"]:
                name = content_bytes[name_node.start_byte:name_node.end_byte].decode("utf8", errors="ignore")
                if name and self._is_valid_identifier(name):
                    symbols.append({
                        "name": name,
                        "type": SymbolType.FUNCTION,
                        "start_line": node.start_point[0] + 1,
                        "end_line": node.end_point[0] + 1,
                        "decorators": []
                    })
                    new_symbol = name
        elif node.type in ["property_definition", "public_field_definition"]:
            # Class variables / properties
            name = self._get_name(node, content_bytes)
            if name and self._is_valid_identifier(name):
                symbols.append({
                    "name": name,
                    "type": SymbolType.VARIABLE,  # Use VARIABLE for class properties
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "decorators": []
                })

        # 2. Identify Imports
        if node.type == "import_statement":
            source_node = node.child_by_field_name("source")
            if source_node:
                target = content_bytes[source_node.start_byte:source_node.end_byte].decode("utf8", errors="ignore").strip("'\"")
                imports.append({
                    "target": target, 
                    "type": "import",
                    "line": source_node.start_point[0],
                    "character": source_node.start_point[1]
                })
        elif node.type == "call_expression":
            fn_node = node.child_by_field_name("function")
            if fn_node and content_bytes[fn_node.start_byte:fn_node.end_byte].decode("utf8", errors="ignore") == "require":
                args_node = node.child_by_field_name("arguments")
                if args_node and len(args_node.children) > 1:
                    first_arg = args_node.children[1]
                    target = content_bytes[first_arg.start_byte:first_arg.end_byte].decode("utf8", errors="ignore").strip("'\"")
                    imports.append({
                        "target": target, 
                        "type": "require",
                        "line": first_arg.start_point[0],
                        "character": first_arg.start_point[1]
                    })

        # 3. Identify Calls
        if node.type == "call_expression" and current_symbol:
            fn_node = node.child_by_field_name("function")
            if fn_node:
                call_name = content_bytes[fn_node.start_byte:fn_node.end_byte].decode("utf8", errors="ignore")
                # Store coordinates for LSP
                calls.append({
                    "caller": current_symbol, 
                    "callee": call_name,
                    "line": fn_node.start_point[0],
                    "character": fn_node.start_point[1]
                })

        # Recurse
        for child in node.children:
            self._walk_tree(child, content_bytes, symbols, imports, calls, new_symbol)

    def _get_name(self, node: Node, content_bytes: bytes) -> str:
        name_node = node.child_by_field_name("name")
        if name_node and name_node.type in ["identifier", "property_identifier", "type_identifier"]:
            return content_bytes[name_node.start_byte:name_node.end_byte].decode("utf8", errors="ignore")
        return ""

    def _is_valid_identifier(self, name: str) -> bool:
        """Strict check for valid symbol names to avoid noise (Skip internal/private)."""
        if not name or len(name) < 3:  # Block fragments and tiny identifiers
            return False
            
        # Skip private methods and properties
        if name.startswith("_"):
            return False
        
        # Blacklist common noisy identifiers used in minified code or as metadata
        blacklist = {"percentage", "data", "index", "value", "props", "type"}
        if name.lower() in blacklist:
            return False
            
        # Ignore common minification patterns
        if name.startswith("G_") or name.startswith("__"):
            return False
            
        import re
        # Must be a standard JS/TS identifier. No leading digits, no spaces, no punctuation.
        is_valid = bool(re.match(r'^[a-zA-Z_$][a-zA-Z0-9_$]*$', name))
        return is_valid
