import pytest
import os
from unittest.mock import patch, mock_open
from testsquad_core.analysis.extractor import SymbolExtractor
from testsquad_shared import SymbolType

def test_python_symbol_extraction():
    extractor = SymbolExtractor()
    content = """
class MyClass:
    def method_one(self):
        pass

def top_level_func():
    return 42
"""
    symbols = extractor.extract_symbols("test.py", content)
    
    names = [s.name for s in symbols]
    assert "MyClass" in names
    assert "method_one" in names
    assert "top_level_func" in names
    
    types = [s.type for s in symbols]
    assert SymbolType.CLASS in types
    assert SymbolType.FUNCTION in types

def test_javascript_symbol_extraction():
    extractor = SymbolExtractor()
    content = """
class MyComponent extends React.Component {
    render() {
        return <div>Hello</div>;
    }
}

const myArrowFunc = (x) => x * 2;

function legacyFunc() {
    console.log("old school");
}
"""
    symbols = extractor.extract_symbols("test.js", content)
    
    names = [s.name for s in symbols]
    assert "MyComponent" in names
    assert "render" in names
    assert "myArrowFunc" in names
    assert "legacyFunc" in names

def test_differ_logic():
    from testsquad_core.analysis.differ import Differ
    diff_content = """--- a/test.py
+++ b/test.py
@@ -1,5 +1,6 @@
 def foo():
-    pass
+    print("hello")
+    return 1
 
-def bar():
+def bar_v2():
     pass
"""
    differ = Differ()
    modified = differ.get_modified_lines(diff_content)
    
    assert "test.py" in modified
    # Added lines in foo are around line 2, 3
    # Added bar_v2 is around line 5
    assert 2 in modified["test.py"]
    assert 5 in modified["test.py"]
