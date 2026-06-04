import ast
import os
from dataclasses import dataclass
from typing import List, Dict, Optional


@dataclass
class Symbol:
    """Represents a code symbol (function, class, method)."""
    name: str
    symbol_type: str  # 'function', 'class', 'method'
    file_path: str
    start_line: int
    end_line: int
    full_signature: Optional[str] = None


def _add_end_linenos(tree, source_lines):
    """Add end_lineno to AST nodes for Python < 3.8 compatibility."""
    if hasattr(next(ast.walk(tree), None), 'end_lineno'):
        return
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        max_line = node.lineno
        for child in ast.walk(node):
            if child is node:
                continue
            if hasattr(child, 'lineno') and child.lineno > max_line:
                max_line = child.lineno
        node.end_lineno = max_line


class SymbolResolver:
    """Resolves covered lines to AST symbol definitions."""
    
    def __init__(self):
        self._cache: Dict[str, List[Symbol]] = {}
    
    def resolve_symbols(self, file_path: str, covered_lines: Dict[str, List[int]]) -> List[Symbol]:
        """
        Given a file path and dict of {line_group: [covered_line_nums]}, 
        resolve which symbols those lines belong to.
        
        Args:
            file_path: Absolute path to Python source file
            covered_lines: Dict with any key, values are lists of line numbers
            
        Returns:
            List of Symbol objects that contain the covered lines
        """
        # Combine all line numbers from any keys
        all_lines = set()
        for lines in covered_lines.values():
            all_lines.update(lines)
        
        if not all_lines:
            return []
        
        # Get or parse the file's symbols
        symbols = self._get_symbols(file_path)
        
        # Filter to only symbols that have covered lines within their range
        result = []
        for sym in symbols:
            symbol_lines = set(range(sym.start_line, sym.end_line + 1))
            if symbol_lines & all_lines:
                result.append(sym)
        
        return result
    
    def _get_symbols(self, file_path: str) -> List[Symbol]:
        """Get all top-level symbols from a file, with caching."""
        if file_path in self._cache:
            return self._cache[file_path]
        
        if not os.path.exists(file_path):
            return []
        
        symbols = []
        try:
            with open(file_path, 'r') as f:
                source = f.read()
            
            tree = ast.parse(source)
            source_lines = source.splitlines()
            _add_end_linenos(tree, source_lines)
            self._collect_symbols(tree, file_path, symbols)
        except SyntaxError as e:
            import logging
            logging.getLogger(__name__).warning(
                f"Syntax error parsing {file_path}: {e}"
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"Failed to parse symbols from {file_path}: {type(e).__name__}: {e}"
            )
        
        self._cache[file_path] = symbols
        return symbols
    
    def _collect_symbols(self, node, file_path: str, symbols: List[Symbol]):
        """Recursively collect all function and class definitions."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef):
                end_line = getattr(child, 'end_lineno', None) or child.lineno
                symbols.append(Symbol(
                    name=child.name,
                    symbol_type="function",
                    file_path=file_path,
                    start_line=child.lineno,
                    end_line=end_line,
                    full_signature=self._get_function_signature(child)
                ))
                self._collect_symbols(child, file_path, symbols)
            elif isinstance(child, ast.AsyncFunctionDef):
                end_line = getattr(child, 'end_lineno', None) or child.lineno
                symbols.append(Symbol(
                    name=child.name,
                    symbol_type="function",
                    file_path=file_path,
                    start_line=child.lineno,
                    end_line=end_line,
                    full_signature=self._get_function_signature(child)
                ))
                self._collect_symbols(child, file_path, symbols)
            elif isinstance(child, ast.ClassDef):
                end_line = getattr(child, 'end_lineno', None) or child.lineno
                symbols.append(Symbol(
                    name=child.name,
                    symbol_type="class",
                    file_path=file_path,
                    start_line=child.lineno,
                    end_line=end_line
                ))
                self._collect_symbols(child, file_path, symbols)
            elif hasattr(child, 'lineno'):
                self._collect_symbols(child, file_path, symbols)

    def _get_function_signature(self, node) -> str:
        """Generate function signature string."""
        args = []
        for arg in node.args.args:
            annotation = ""
            if arg.annotation:
                try:
                    annotation = f": {ast.unparse(arg.annotation)}"
                except:
                    pass
            args.append(f"{arg.arg}{annotation}")
        
        returns = ""
        if node.returns:
            try:
                returns = f" -> {ast.unparse(node.returns)}"
            except:
                pass
        
        return f"def {node.name}({', '.join(args)}){returns}"