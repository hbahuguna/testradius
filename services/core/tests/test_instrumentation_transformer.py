import pytest
from unittest.mock import MagicMock, patch
from testsquad_core.instrumentation.symbol_resolver import Symbol


class TestInstrumentationTransformer:
    """Tests for the per-test coverage transformer."""

    def test_transform_per_test_coverage_to_mappings(self):
        """Converts per-test coverage data to TestSymbolMapping objects."""
        from testsquad_core.instrumentation.transformer import InstrumentationTransformer
        
        # Per-test coverage data (what the plugin produces)
        per_test_coverage = {
            "tests/test_math.py::test_add": {
                "src/math.py": [2, 3, 4, 5],  # lines in add() function
                "src/utils.py": [10, 11]
            },
            "tests/test_math.py::test_subtract": {
                "src/math.py": [12, 13, 14, 15]  # lines in subtract() function
            }
        }
        
        transformer = InstrumentationTransformer()
        
        # Mock the symbol resolver to return test symbols
        with patch.object(transformer.symbol_resolver, 'resolve_symbols') as mock_resolve:
            mock_resolve.side_effect = [
                [Symbol(name="add", symbol_type="function", file_path="src/math.py", start_line=2, end_line=10)],
                [Symbol(name="helper", symbol_type="function", file_path="src/utils.py", start_line=10, end_line=15)],
                [Symbol(name="subtract", symbol_type="function", file_path="src/math.py", start_line=12, end_line=20)]
            ]
            
            mappings = transformer.transform(per_test_coverage)
            
            assert len(mappings) == 2
            
            # First test (test_add) covers add and helper
            test_add_mapping = next(m for m in mappings if "test_add" in m["test_name"])
            symbol_names = [s.name for s in test_add_mapping["symbols"]]
            assert "add" in symbol_names
            assert "helper" in symbol_names
            
            # Second test (test_subtract) covers subtract
            test_sub_mapping = next(m for m in mappings if "test_subtract" in m["test_name"])
            symbol_names = [s.name for s in test_sub_mapping["symbols"]]
            assert "subtract" in symbol_names

    def test_handles_empty_coverage(self):
        """Empty per-test coverage returns empty mappings."""
        from testsquad_core.instrumentation.transformer import InstrumentationTransformer
        
        transformer = InstrumentationTransformer()
        mappings = transformer.transform({})
        
        assert mappings == []

    def test_handles_test_with_no_covered_source(self):
        """A test that doesn't cover any source files is skipped."""
        from testsquad_core.instrumentation.transformer import InstrumentationTransformer
        
        transformer = InstrumentationTransformer()
        
        per_test_coverage = {
            "tests/test_math.py::test_empty": {}  # no source coverage
        }
        
        mappings = transformer.transform(per_test_coverage)
        
        # Should produce a mapping but with empty symbols
        assert len(mappings) == 1
        assert len(mappings[0]["symbols"]) == 0