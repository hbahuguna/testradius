import pytest
import tempfile
import os
from pathlib import Path


class TestSymbolResolver:
    """Tests for SymbolResolver - maps covered lines to AST symbols."""

    def test_resolve_function_from_covered_lines(self):
        """Given covered lines, resolve to the function that contains them."""
        from testsquad_core.instrumentation.symbol_resolver import SymbolResolver
        
        # Create a temp Python file with a function
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("""
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b
""")
            temp_file = f.name
        
        try:
            resolver = SymbolResolver()
            # Lines 2-3 are the add function body
            covered_lines = {"add": [2, 3, 4]}
            symbols = resolver.resolve_symbols(temp_file, covered_lines)
            
            assert len(symbols) >= 1
            assert any(s.name == "add" for s in symbols)
        finally:
            os.unlink(temp_file)

    def test_match_lines_to_symbols(self):
        """Line numbers within a function's range map to that function."""
        from testsquad_core.instrumentation.symbol_resolver import SymbolResolver
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("""
def outer():
    def inner():
        return 1
    return inner()

class MyClass:
    def method(self):
        pass
""")
            temp_file = f.name
        
        try:
            resolver = SymbolResolver()
            # Line 4 is inside inner(), should map to inner not outer
            covered_lines = {"inner": [4]}
            symbols = resolver.resolve_symbols(temp_file, covered_lines)
            
            symbol_names = [s.name for s in symbols]
            assert "inner" in symbol_names
        finally:
            os.unlink(temp_file)

    def test_class_and_methods(self):
        """Lines in methods map to both class and method symbols."""
        from testsquad_core.instrumentation.symbol_resolver import SymbolResolver
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("""
class Calculator:
    def add(self, a, b):
        return a + b
    
    def subtract(self, a, b):
        return a - b
""")
            temp_file = f.name
        
        try:
            resolver = SymbolResolver()
            covered_lines = {"calc": [4, 5, 6]}
            symbols = resolver.resolve_symbols(temp_file, covered_lines)
            
            # Should capture the method
            assert any(s.name == "add" for s in symbols)
        finally:
            os.unlink(temp_file)

    def test_async_functions(self):
        """Async functions are handled the same as sync functions."""
        from testsquad_core.instrumentation.symbol_resolver import SymbolResolver
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("""
async def async_fetch(url):
    return url

def sync_wrapper():
    return "sync"
""")
            temp_file = f.name
        
        try:
            resolver = SymbolResolver()
            covered_lines = {"async_fetch": [2, 3]}
            symbols = resolver.resolve_symbols(temp_file, covered_lines)
            
            assert any(s.name == "async_fetch" for s in symbols)
        finally:
            os.unlink(temp_file)

    def test_empty_coverage_returns_empty(self):
        """No covered lines returns empty symbol list."""
        from testsquad_core.instrumentation.symbol_resolver import SymbolResolver
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def foo():\n    pass")
            temp_file = f.name
        
        try:
            resolver = SymbolResolver()
            symbols = resolver.resolve_symbols(temp_file, {})
            assert symbols == []
        finally:
            os.unlink(temp_file)

    def test_lines_outside_symbols_are_ignored(self):
        """Covered lines not in any function are silently dropped."""
        from testsquad_core.instrumentation.symbol_resolver import SymbolResolver
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("def foo():\n    pass\n\n# comment\nx = 1")
            temp_file = f.name
        
        try:
            resolver = SymbolResolver()
            # Line 5 is just x = 1, not in any function
            covered_lines = {"test": [1, 2, 5]}
            symbols = resolver.resolve_symbols(temp_file, covered_lines)
            
            # Should only get foo, not the random line 5
            assert len(symbols) == 1
            assert symbols[0].name == "foo"
        finally:
            os.unlink(temp_file)