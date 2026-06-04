import os
from typing import List, Optional
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript
from tree_sitter import Language, Parser, Node
from testsquad_shared import CodeSymbol, SymbolType

class SymbolExtractor:
    def __init__(self):
        self.py_language = Language(tspython.language(), "python")
        self.js_language = Language(tsjavascript.language(), "javascript")
        
        self.py_parser = Parser()
        self.py_parser.set_language(self.py_language)
        
        self.js_parser = Parser()
        self.js_parser.set_language(self.js_language)

    def extract_symbols(self, file_path: str, content: str) -> List[CodeSymbol]:
        if file_path.endswith(".py"):
            return self._extract_python_symbols(file_path, content)
        elif file_path.endswith((".js", ".jsx", ".ts", ".tsx")):
            return self._extract_javascript_symbols(file_path, content)
        return []

    def _extract_python_symbols(self, file_path: str, content: str) -> List[CodeSymbol]:
        tree = self.py_parser.parse(bytes(content, "utf8"))
        symbols = []
        self._walk_tree(tree.root_node, file_path, content, symbols, "python")
        return symbols

    def _extract_javascript_symbols(self, file_path: str, content: str) -> List[CodeSymbol]:
        tree = self.js_parser.parse(bytes(content, "utf8"))
        symbols = []
        self._walk_tree(tree.root_node, file_path, content, symbols, "javascript")
        return symbols

    def _walk_tree(self, node: Node, file_path: str, content: str, symbols: List[CodeSymbol], lang: str):
        symbol_type = None
        name = None

        if lang == "python":
            if node.type == "function_definition":
                symbol_type = SymbolType.FUNCTION
                # Find the name child
                for child in node.children:
                    if child.type == "identifier":
                        name = content[child.start_byte:child.end_byte]
                        break
            elif node.type == "class_definition":
                symbol_type = SymbolType.CLASS
                for child in node.children:
                    if child.type == "identifier":
                        name = content[child.start_byte:child.end_byte]
                        break
        elif lang == "javascript":
            # Basic JS extraction: function declarations, class declarations, arrow functions assigned to const
            if node.type in ["function_declaration", "method_definition"]:
                symbol_type = SymbolType.FUNCTION
                for child in node.children:
                    if child.type == "identifier" or child.type == "property_identifier":
                        name = content[child.start_byte:child.end_byte]
                        break
            elif node.type == "class_declaration":
                symbol_type = SymbolType.CLASS
                for child in node.children:
                    if child.type == "identifier":
                        name = content[child.start_byte:child.end_byte]
                        break
            elif node.type == "variable_declarator":
                # Check for const foo = () => ...
                is_func = False
                for child in node.children:
                    if child.type in ["arrow_function", "function_expression"]:
                        is_func = True
                        break
                if is_func:
                    symbol_type = SymbolType.FUNCTION
                    for child in node.children:
                        if child.type == "identifier":
                            name = content[child.start_byte:child.end_byte]
                            break

        if symbol_type and name:
            symbols.append(CodeSymbol(
                name=name,
                type=symbol_type,
                file_path=file_path,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                content=content[node.start_byte:node.end_byte]
            ))

        for child in node.children:
            self._walk_tree(child, file_path, content, symbols, lang)
