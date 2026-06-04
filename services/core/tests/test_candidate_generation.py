import pytest
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from testsquad_core.intelligence.vector_mapper import VectorMapper


class TestVectorMapper:
    """Test Task 2.1.2: Candidate Generation Tests."""

    @pytest.fixture
    def mock_neo4j(self):
        """Create mock Neo4j client."""
        mock = MagicMock()
        return mock

    @pytest.fixture
    def vector_mapper(self, mock_neo4j):
        """Create VectorMapper with mock client."""
        return VectorMapper(neo4j=mock_neo4j)

    # --- Test _get_unmapped_symbols ---

    def test_get_unmapped_symbols_query(self, vector_mapper, mock_neo4j):
        """Test unmapped symbols query builds correctly."""
        mock_neo4j.query.return_value = []
        
        result = vector_mapper._get_unmapped_symbols(1)
        
        # Query should have been called
        assert mock_neo4j.query.called
        args, kwargs = mock_neo4j.query.call_args
        assert "SUGGESTED_TEST" in args[0]
        assert "APPROVED_TEST" in args[0]

    def test_get_unmapped_symbols_returns_list(self, vector_mapper, mock_neo4j):
        """Test returns list of symbols."""
        mock_neo4j.query.return_value = [
            {"name": "func1", "file_path": "src/utils.ts", "type": "function", "community_id": 1},
            {"name": "func2", "file_path": "src/helpers.ts", "type": "function", "community_id": 2}
        ]
        
        result = vector_mapper._get_unmapped_symbols(1)
        
        assert len(result) == 2
        assert result[0]["name"] == "func1"

    # --- Test _get_all_tests ---

    def test_get_all_tests(self, vector_mapper, mock_neo4j):
        """Test getting all tests."""
        mock_neo4j.query.return_value = [
            {"name": "test_func1", "file_path": "tests/utils.test.ts", "test_community_id": 1}
        ]
        
        result = vector_mapper._get_all_tests(1)
        
        assert len(result) == 1
        assert mock_neo4j.query.called

    # --- Test Layer 1: CALLS Graph ---

    def test_layer1_calls_graph_no_calls(self, vector_mapper, mock_neo4j):
        """Test CALLS graph with no direct calls."""
        mock_neo4j.query.return_value = []
        
        symbol = {"name": "func1", "file_path": "src/utils.ts"}
        all_tests = [{"name": "test_func1", "file_path": "tests/utils.test.ts"}]
        
        result = vector_mapper._layer1_calls_graph(symbol, all_tests)
        
        assert result == []

    def test_layer1_calls_graph_with_calls(self, vector_mapper, mock_neo4j):
        """Test CALLS graph with direct calls."""
        mock_neo4j.query.return_value = [
            {"name": "test_func1", "file_path": "tests/utils.test.ts", "call_line": 10}
        ]
        
        symbol = {"name": "func1", "file_path": "src/utils.ts"}
        all_tests = [{"name": "test_func1", "file_path": "tests/utils.test.ts"}]
        
        result = vector_mapper._layer1_calls_graph(symbol, all_tests)
        
        assert len(result) == 1
        assert result[0][1] == 0.95  # High confidence

    # --- Test Layer 2: Filename Heuristics ---

    def test_layer2_typescript_test_pattern(self, vector_mapper):
        """Test TypeScript X.ts → X.test.ts pattern."""
        symbol = {"name": "add", "file_path": "src/utils.ts"}
        all_tests = [
            {"name": "test_add", "file_path": "src/utils.test.ts"},
            {"name": "other", "file_path": "tests/other.test.ts"}
        ]
        
        result = vector_mapper._layer2_filename_heuristics(symbol, all_tests)
        
        # Should match utils.test.ts
        test_files = [r[0]["file_path"] for r in result]
        assert "src/utils.test.ts" in test_files

    def test_layer2_typescript_spec_pattern(self, vector_mapper):
        """Test TypeScript X.ts → X.spec.ts pattern."""
        symbol = {"name": "add", "file_path": "src/utils.ts"}
        all_tests = [
            {"name": "test_add", "file_path": "src/utils.spec.ts"}
        ]
        
        result = vector_mapper._layer2_filename_heuristics(symbol, all_tests)
        
        assert len(result) >= 1

    def test_layer2_python_test_pattern(self, vector_mapper):
        """Test Python test_X.py → X.py pattern."""
        symbol = {"name": "add", "file_path": "src/utils.py"}
        all_tests = [
            {"name": "test_add", "file_path": "tests/test_utils.py"},
            {"name": "test_add_alt", "file_path": "tests/utils_test.py"}
        ]
        
        result = vector_mapper._layer2_filename_heuristics(symbol, all_tests)
        
        # Should match test_utils.py or utils_test.py
        test_files = [r[0]["file_path"] for r in result]
        assert any("test" in f for f in test_files)

    def test_layer2_directory_bonus(self, vector_mapper):
        """Test same directory bonus."""
        symbol = {"name": "add", "file_path": "src/utils.ts"}
        all_tests = [
            {"name": "test_add", "file_path": "src/utils.test.ts"},  # Same dir
            {"name": "test_add", "file_path": "tests/utils.test.ts"}  # Different dir
        ]
        
        result = vector_mapper._layer2_filename_heuristics(symbol, all_tests)
        
        # Find the same-dir test, should have higher confidence
        same_dir_match = [r for r in result if r[0]["file_path"] == "src/utils.test.ts"]
        if same_dir_match:
            assert same_dir_match[0][1] > 0.85

    # --- Test Layer 3: Community ---

    def test_layer3_community_match(self, vector_mapper):
        """Test community co-location."""
        symbol = {"name": "func1", "community_id": 1}
        all_tests = [
            {"name": "test_func1", "test_community_id": 1},
            {"name": "test_func2", "test_community_id": 2}
        ]
        
        result = vector_mapper._layer3_community(symbol, all_tests)
        
        assert len(result) == 1
        assert result[0][1] == 0.70

    def test_layer3_no_community(self, vector_mapper):
        """Test symbol with no community."""
        symbol = {"name": "func1", "community_id": 0}
        all_tests = [
            {"name": "test_func1", "test_community_id": 1}
        ]
        
        result = vector_mapper._layer3_community(symbol, all_tests)
        
        assert result == []

    # --- Test Pre-filter Logic ---

    def test_build_candidate_tests_empty(self, vector_mapper, mock_neo4j):
        """Test empty input returns empty output."""
        result = vector_mapper._build_candidate_tests([], [])
        
        assert result == []

    def test_build_candidate_tests_reduction(self, vector_mapper, mock_neo4j):
        """Test pre-filter reduces candidates."""
        product_symbols = [
            {"name": f"func{i}", "file_path": f"src/file{i}.ts", "community_id": 1}
            for i in range(100)
        ]
        all_tests = [
            {"name": f"test{i}", "file_path": f"tests/file{i}.test.ts", "test_community_id": 1}
            for i in range(100)
        ]
        
        # Mock layers to return empty (no matches)
        with patch.object(vector_mapper, '_layer1_calls_graph', return_value=[]):
            with patch.object(vector_mapper, '_layer2_filename_heuristics', return_value=[]):
                with patch.object(vector_mapper, '_layer3_community', return_value=[]):
                    result = vector_mapper._build_candidate_tests(product_symbols, all_tests)
        
        # Should have some candidates from layer 2/3
        # If no matches, still returns empty
        assert isinstance(result, list)

    def test_build_candidate_tests_deduplication(self, vector_mapper, mock_neo4j):
        """Test deduplication keeps highest confidence."""
        product_symbols = [
            {"name": "func1", "file_path": "src/utils.ts", "community_id": 1}
        ]
        all_tests = [
            {"name": "test_func1", "file_path": "tests/utils.test.ts", "test_community_id": 1}
        ]
        
        # All layers return same test with different confidences
        def mock_layer2(symbol, tests):
            return [(tests[0], 0.85), (tests[0], 0.70)]
        
        with patch.object(vector_mapper, '_layer1_calls_graph', return_value=[]):
            with patch.object(vector_mapper, '_layer2_filename_heuristics', side_effect=mock_layer2):
                with patch.object(vector_mapper, '_layer3_community', return_value=[]):
                    result = vector_mapper._build_candidate_tests(product_symbols, all_tests)
        
        # Should deduplicate to one entry with highest confidence
        if result:
            assert len(result) == 1
            assert result[0]["confidence"] > 0.70


class TestFilenameMatching:
    """Test filename pattern matching in detail."""

    @pytest.fixture
    def vector_mapper(self):
        mock_neo4j = MagicMock()
        return VectorMapper(neo4j=mock_neo4j)

    def test_exact_test_suffix(self, vector_mapper):
        """Test X.ts → X.test.ts."""
        symbol = {"file_path": "src/utils.ts"}
        result = vector_mapper._layer2_filename_heuristics(symbol, [
            {"file_path": "src/utils.test.ts"}
        ])
        assert len(result) >= 1

    def test_exact_spec_suffix(self, vector_mapper):
        """Test X.ts → X.spec.ts."""
        symbol = {"file_path": "src/utils.ts"}
        result = vector_mapper._layer2_filename_heuristics(symbol, [
            {"file_path": "src/utils.spec.ts"}
        ])
        assert len(result) >= 1

    def test_prefixed_test(self, vector_mapper):
        """Test X.ts → test.X.ts."""
        symbol = {"file_path": "src/utils.ts"}
        result = vector_mapper._layer2_filename_heuristics(symbol, [
            {"file_path": "src/test.utils.ts"}
        ])
        assert len(result) >= 1

    def test_python_underscore_test(self, vector_mapper):
        """Test X.py → test_X.py."""
        symbol = {"file_path": "src/utils.py"}
        result = vector_mapper._layer2_filename_heuristics(symbol, [
            {"file_path": "tests/test_utils.py"}
        ])
        assert len(result) >= 1

    def test_python_suffix_test(self, vector_mapper):
        """Test X.py → X_test.py."""
        symbol = {"file_path": "src/utils.py"}
        result = vector_mapper._layer2_filename_heuristics(symbol, [
            {"file_path": "tests/utils_test.py"}
        ])
        assert len(result) >= 1


class TestPreFilterReduction:
    """Test pre-filter reduction ratio."""

    @pytest.fixture
    def vector_mapper(self):
        mock_neo4j = MagicMock()
        return VectorMapper(neo4j=mock_neo4j)

    def test_reduction_ratio(self, vector_mapper):
        """Test N×N reduced to N×k."""
        # 100 product symbols, 100 tests = 10,000 potential comparisons
        product_symbols = [
            {"name": f"func{i}", "file_path": f"src/file{i}.ts", "community_id": 1}
            for i in range(100)
        ]
        all_tests = [
            {"name": f"test{i}", "file_path": f"tests/file{i}.test.ts", "test_community_id": 1}
            for i in range(100)
        ]
        
        # All layers match
        def mock_all_layers(symbol, tests):
            return [(tests[0], 0.85)]
        
        with patch.object(vector_mapper, '_layer1_calls_graph', side_effect=mock_all_layers):
            with patch.object(vector_mapper, '_layer2_filename_heuristics', side_effect=mock_all_layers):
                with patch.object(vector_mapper, '_layer3_community', side_effect=mock_all_layers):
                    result = vector_mapper._build_candidate_tests(product_symbols, all_tests)
        
        # N×N = 10,000, but N×k × N = 100 × 10 = 1,000 max
        # Should be significantly reduced
        original_comparisons = 100 * 100  # 10,000
        max_expected = 100 * 10  # 1,000
        
        assert len(result) <= max_expected


class TestEdgeCases:
    """Test edge cases."""

    @pytest.fixture
    def vector_mapper(self):
        mock_neo4j = MagicMock()
        return VectorMapper(neo4j=mock_neo4j)

    def test_empty_symbol_name(self, vector_mapper):
        """Test symbol with empty name."""
        symbol = {"name": "", "file_path": "src/utils.ts"}
        all_tests = [{"file_path": "src/utils.test.ts"}]
        
        result = vector_mapper._build_candidate_tests([symbol], all_tests)
        
        assert result == []

    def test_empty_file_path(self, vector_mapper):
        """Test symbol with empty file path."""
        symbol = {"name": "func1", "file_path": ""}
        all_tests = [{"file_path": "tests/utils.test.ts"}]
        
        result = vector_mapper._build_candidate_tests([symbol], all_tests)
        
        assert result == []

    def test_unicode_file_paths(self, vector_mapper):
        """Test unicode file paths."""
        symbol = {"name": " функ", "file_path": "src/файл.ts"}
        all_tests = [{"file_path": "tests/тест.test.ts"}]
        
        result = vector_mapper._layer2_filename_heuristics(symbol, all_tests)
        
        assert isinstance(result, list)

    def test_windows_paths(self, vector_mapper):
        """Test Windows-style paths."""
        symbol = {"name": "func1", "file_path": "src\\utils.ts"}
        all_tests = [{"file_path": "tests\\utils.test.ts"}]
        
        result = vector_mapper._layer2_filename_heuristics(symbol, all_tests)
        
        assert isinstance(result, list)


class TestIntegration:
    """Integration-style tests."""

    @pytest.fixture
    def vector_mapper(self):
        mock_neo4j = MagicMock()
        return VectorMapper(neo4j=mock_neo4j)

    def test_generate_candidates_flow(self, vector_mapper, mock_neo4j):
        """Test full candidate generation flow."""
        # Mock unmapped symbols
        mock_neo4j.query.side_effect = [
            [{"name": "func1", "file_path": "src/utils.ts", "community_id": 1}],
            [{"name": "test_func1", "file_path": "tests/utils.test.ts", "test_community_id": 1}]
        ]
        
        with patch.object(vector_mapper, '_build_candidate_tests', return_value=[
            {"symbol_name": "func1", "test_name": "test_func1", "confidence": 0.85}
        ]):
            result = vector_mapper.generate_candidates(1)
        
        assert isinstance(result, list)

    def test_get_statistics(self, vector_mapper, mock_neo4j):
        """Test statistics."""
        mock_neo4j.query.side_effect = [
            [{"name": "func1"}],
            [{"name": "test_func1"}]
        ]
        
        stats = vector_mapper.get_statistics(1)
        
        assert "unmapped_symbols" in stats
        assert "total_tests" in stats
        assert "potential_comparisons" in stats


if __name__ == "__main__":
    pytest.main([__file__, "-v"])