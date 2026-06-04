import pytest
from unittest.mock import MagicMock, patch, mock_open
from testsquad_core.graph.resolvers.python import PythonResolver
from testsquad_shared import SymbolType

def test_python_resolver_symbols():
    resolver = PythonResolver()
    content = """
import math
from os import path

class DataProcessor:
    def process(self, x):
        return math.sqrt(x)

def main():
    p = DataProcessor()
    return p.process(16)
"""
    symbols, imports, calls = resolver.resolve_relationships("test.py", content)
    
    # 1. Verify Symbols
    sym_names = {s["name"]: s for s in symbols}
    assert "DataProcessor" in sym_names
    assert sym_names["DataProcessor"]["type"] == SymbolType.CLASS
    assert "process" in sym_names
    assert "main" in sym_names

    # 2. Verify Imports
    imp_targets = {i["target"] for i in imports}
    assert "math" in imp_targets
    assert "os" in imp_targets

    # 3. Verify Calls
    # main calls DataProcessor (constructor) and process
    caller_main = [c for c in calls if c["caller"] == "main"]
    callees = {c["callee"] for c in caller_main}
    assert "DataProcessor" in callees
    assert "process" in callees
    
    # process calls sqrt
    caller_process = [c for c in calls if c["caller"] == "process"]
    assert caller_process[0]["callee"] == "sqrt"

def test_ingestor_orchestration():
    mock_neo4j = MagicMock()
    from testsquad_core.graph.ingestor import GraphIngestor
    
    ingestor = GraphIngestor(mock_neo4j, project_id=1)
    
    # Mock file system
    with patch("os.walk") as mock_walk, \
         patch("builtins.open", mock_open(read_data="def foo(): pass")):
        
        mock_walk.return_value = [
            (".", ["subdir"], ["root.py"]),
            ("./subdir", [], ["child.py"])
        ]
        
        ingestor.ingest_repo(".")
        
        # Verify Neo4j calls
        assert mock_neo4j.ensure_constraints.called
        # 2 files indexed
        assert mock_neo4j.index_file.call_count == 2
        # foo indexed twice (once per file)
        assert mock_neo4j.index_symbol.call_count == 2
