import ast
import os
from dataclasses import dataclass
from typing import List, Dict, Optional

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


@dataclass
class Symbol:
    """Represents a code symbol (function, class, method)."""
    name: str
    symbol_type: str  # 'function', 'class', 'method', 'async_function'
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
        return select_innermost_owners(self._get_symbols(file_path), covered_lines)

    def get_symbols(self, file_path: str) -> List[Symbol]:
        """Return every symbol defined in ``file_path`` (no coverage filter).

        Used by the diff analyzer, which decides which symbol changed from the
        diff hunk itself.
        """
        return self._get_symbols(file_path)
    
    def _get_symbols(self, file_path: str) -> List[Symbol]:
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
        """Recursively collect class, function, and method definitions.

        Symbols keep their **bare** name (no class prefix). Same-named methods
        in different classes are told apart downstream by their line span — both
        in the ``Symbol`` node identity (``neo4j_store``) and in the
        module-qualified ``qualified_name`` computed by ``instrumentation/diff_parser``.
        """
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                end_line = getattr(child, 'end_lineno', None) or child.lineno
                symbols.append(Symbol(
                    name=child.name,
                    symbol_type="class",
                    file_path=file_path,
                    start_line=child.lineno,
                    end_line=end_line
                ))
                self._collect_symbols(child, file_path, symbols)
            elif isinstance(child, ast.FunctionDef):
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
                    symbol_type="async_function",
                    file_path=file_path,
                    start_line=child.lineno,
                    end_line=end_line,
                    full_signature=self._get_function_signature(child)
                ))
                self._collect_symbols(child, file_path, symbols)
            elif hasattr(child, 'lineno'):
                self._collect_symbols(child, file_path, symbols)

    def _get_function_signature(self, node) -> str:
        args = []
        for arg in node.args.args:
            annotation = ""
            if arg.annotation:
                try:
                    annotation = f": {ast.unparse(arg.annotation)}"
                except Exception:
                    pass
            args.append(f"{arg.arg}{annotation}")
        returns = ""
        if node.returns:
            try:
                returns = f" -> {ast.unparse(node.returns)}"
            except Exception:
                pass
        return f"def {node.name}({', '.join(args)}){returns}"
