from typing import Dict, List, Any
from .symbol_resolver import SymbolResolver, Symbol


class InstrumentationTransformer:
    """Transforms per-test coverage data to test-symbol mappings."""
    
    def __init__(self):
        self.symbol_resolver = SymbolResolver()
    
    def transform(self, per_test_coverage: Dict[str, Dict[str, List[int]]]) -> List[Dict[str, Any]]:
        """
        Transform per-test coverage data to mappings.
        
        Args:
            per_test_coverage: Dict mapping test_id -> {file_path -> [covered_line_nums]}
            
        Returns:
            List of dicts with test_name, test_file, symbols
        """
        mappings = []
        
        for test_id, file_coverage in per_test_coverage.items():
            # Parse test_id into test_name and test_file
            test_name, test_file = self._parse_test_id(test_id)
            
            if not test_file:
                continue
            
            # Resolve each file's covered lines to symbols
            all_symbols = []
            for file_path, covered_lines in file_coverage.items():
                if not covered_lines:
                    continue
                    
                # Create a dict with the covered lines
                covered_lines_dict = {"test": covered_lines}
                symbols = self.symbol_resolver.resolve_symbols(file_path, covered_lines_dict)
                all_symbols.extend(symbols)
            
            mappings.append({
                "test_name": test_name,
                "test_file": test_file,
                "symbols": all_symbols
            })
        
        return mappings
    
    def _parse_test_id(self, test_id: str) -> tuple:
        """Parse pytest nodeid into (test_name, test_file)."""
        # Example: "tests/test_math.py::test_add" -> "test_add", "tests/test_math.py"
        # Or: "tests/test_math.py::TestClass::test_method" -> "test_method", "tests/test_math.py"
        
        if "::" in test_id:
            parts = test_id.split("::")
            test_file = parts[0]
            # Last part is the test name/function
            test_name = parts[-1]
        else:
            test_file = test_id
            test_name = ""
        
        return test_name, test_file