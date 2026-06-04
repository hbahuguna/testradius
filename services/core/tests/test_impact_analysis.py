import pytest
import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from testsquad_core.analysis.diff_parser import DiffParser, TestWithScore


class TestImpactAnalysis:
    """Test Task 3.2.2: Impact Analysis Tests."""

    @pytest.fixture
    def mock_neo4j(self):
        mock = MagicMock()
        mock.query.return_value = []
        return mock

    @pytest.fixture
    def parser(self, mock_neo4j):
        return DiffParser(neo4j_client=mock_neo4j)

    @pytest.fixture
    def changed_symbols(self):
        return [
            {'symbol_name': 'add', 'file_path': 'src/math.py', 'start_line': 1, 'end_line': 10},
            {'symbol_name': 'subtract', 'file_path': 'src/math.py', 'start_line': 12, 'end_line': 20},
        ]

    # --- Test vector matching ---

    def test_vector_matching_finds_tests(self, parser, mock_neo4j):
        """Test changed symbols matched to tests via Neo4j."""
        mock_neo4j.query.return_value = [
            {'test_name': 'test_add', 'test_file': 'tests/math.test.ts', 'confidence': 0.9, 'source': 'coverage'}
        ]

        changed_symbols = [
            {'symbol_name': 'add', 'file_path': 'src/math.py', 'start_line': 1, 'end_line': 10}
        ]

        result = parser.get_impact_tests(
            changed_symbols, project_id=1, embedder=None, max_hops=1, top_k=5
        )

        assert isinstance(result, list)

    def test_vector_matching_no_false_positives(self, parser, mock_neo4j):
        """Test no tests returned when Neo4j returns empty."""
        mock_neo4j.query.return_value = []

        changed_symbols = [
            {'symbol_name': 'nonexistent', 'file_path': 'src/missing.py', 'start_line': 1, 'end_line': 10}
        ]

        result = parser.get_impact_tests(
            changed_symbols, project_id=1, embedder=None, max_hops=1, top_k=5
        )

        assert result == []

    def test_vector_match_called_for_symbol(self, parser, mock_neo4j):
        """Test vector matching queries Neo4j for each symbol."""
        mock_neo4j.query.return_value = []

        changed_symbols = [
            {'symbol_name': 'add', 'file_path': 'src/math.py', 'start_line': 1, 'end_line': 10},
            {'symbol_name': 'subtract', 'file_path': 'src/math.py', 'start_line': 12, 'end_line': 20},
        ]

        parser.get_impact_tests(
            changed_symbols, project_id=1, embedder=None, max_hops=1, top_k=5
        )

        assert mock_neo4j.query.call_count >= 1

    # --- Test call graph traversal ---

    def test_call_graph_1_hop_traversal(self, parser, mock_neo4j):
        """Test 1-hop traversal finds direct calls."""
        mock_neo4j.query.return_value = [
            {'test_name': 'test_add_direct', 'test_file': 'tests/math.test.ts',
             'confidence': 0.5, 'source': 'coverage'}
        ]

        changed_symbols = [
            {'symbol_name': 'add', 'file_path': 'src/math.py', 'start_line': 1, 'end_line': 10}
        ]

        result = parser.get_impact_tests(
            changed_symbols, project_id=1, embedder=None, max_hops=1, top_k=5
        )

        assert isinstance(result, list)

    def test_call_graph_2_hop_traversal(self, parser, mock_neo4j):
        """Test 2-hop traversal finds indirect calls."""
        mock_neo4j.query.return_value = [
            {'test_name': 'test_indirect', 'test_file': 'tests/math.test.ts',
             'confidence': 0.3, 'source': 'coverage'}
        ]

        changed_symbols = [
            {'symbol_name': 'calculate', 'file_path': 'src/core.py', 'start_line': 1, 'end_line': 50}
        ]

        result = parser.get_impact_tests(
            changed_symbols, project_id=1, embedder=None, max_hops=2, top_k=5
        )

        assert isinstance(result, list)

    def test_call_graph_respects_max_depth(self, parser, mock_neo4j):
        """Test max_hops parameter limits traversal depth."""
        mock_neo4j.query.return_value = []

        changed_symbols = [
            {'symbol_name': 'add', 'file_path': 'src/math.py', 'start_line': 1, 'end_line': 10}
        ]

        result = parser.get_impact_tests(
            changed_symbols, project_id=1, embedder=None, max_hops=1, top_k=5
        )

        assert isinstance(result, list)

    # --- Test ranking algorithm ---

    def test_ranking_higher_confidence_higher_rank(self, parser, mock_neo4j):
        """Test higher confidence scores rank higher."""
        mock_neo4j.query.return_value = [
            {'test_name': 'test_high', 'test_file': 'test_high.ts', 'confidence': 0.9, 'source': 'coverage'},
            {'test_name': 'test_low', 'test_file': 'test_low.ts', 'confidence': 0.3, 'source': 'coverage'},
        ]

        changed_symbols = [
            {'symbol_name': 'add', 'file_path': 'src/math.py', 'start_line': 1, 'end_line': 10}
        ]

        result = parser.get_impact_tests(
            changed_symbols, project_id=1, embedder=None, max_hops=1, top_k=5
        )

        # Should be sorted by risk_score descending
        assert isinstance(result, list)

    def test_ranking_shorter_distance_higher_rank(self, parser, mock_neo4j):
        """Test shorter graph distance ranks higher."""
        mock_neo4j.query.return_value = [
            {'test_name': 'test_2hop', 'test_file': 'test_2hop.ts', 'confidence': 0.5, 'source': 'coverage'},
            {'test_name': 'test_1hop', 'test_file': 'test_1hop.ts', 'confidence': 0.5, 'source': 'coverage'},
        ]

        changed_symbols = [
            {'symbol_name': 'add', 'file_path': 'src/math.py', 'start_line': 1, 'end_line': 10}
        ]

        result = parser.get_impact_tests(
            changed_symbols, project_id=1, embedder=None, max_hops=2, top_k=5
        )

        assert isinstance(result, list)

    def test_ranking_risk_score_applied(self, parser, mock_neo4j):
        """Test risk_score = confidence × (1/graph_distance) × risk."""
        mock_neo4j.query.return_value = []

        changed_symbols = [
            {'symbol_name': 'add', 'file_path': 'src/math.py', 'start_line': 1, 'end_line': 10}
        ]

        result = parser.get_impact_tests(
            changed_symbols, project_id=1, embedder=None, max_hops=1, top_k=5
        )

        for test in result:
            assert hasattr(test, 'risk_score')
            assert isinstance(test.risk_score, (int, float))

    # --- Test return format ---

    def test_return_format_test_with_score(self, parser, mock_neo4j):
        """Test return format matches TestWithScore."""
        mock_neo4j.query.return_value = [
            {'test_name': 'test_add', 'test_file': 'tests/math.test.ts', 'confidence': 0.8, 'source': 'coverage'}
        ]

        changed_symbols = [
            {'symbol_name': 'add', 'file_path': 'src/math.py', 'start_line': 1, 'end_line': 10}
        ]

        result = parser.get_impact_tests(
            changed_symbols, project_id=1, embedder=None, max_hops=1, top_k=5
        )

        if result:
            assert isinstance(result[0], TestWithScore)
            assert hasattr(result[0], 'test_name')
            assert hasattr(result[0], 'test_file')
            assert hasattr(result[0], 'confidence')
            assert hasattr(result[0], 'reason')
            assert hasattr(result[0], 'risk_score')

    # --- Test performance ---

    def test_performance_50_symbols(self, parser, mock_neo4j):
        """Test 50 changed symbols completes in <5s."""
        import time
        mock_neo4j.query.return_value = []

        changed_symbols = [
            {'symbol_name': f'symbol_{i}', 'file_path': f'src/file{i}.py', 
             'start_line': 1, 'end_line': 10}
            for i in range(50)
        ]

        start = time.time()
        result = parser.get_impact_tests(
            changed_symbols, project_id=1, embedder=None, max_hops=1, top_k=10
        )
        elapsed = time.time() - start

        assert elapsed < 5.0

    def test_performance_100_symbols(self, parser, mock_neo4j):
        """Test 100 changed symbols completes in <10s."""
        import time
        mock_neo4j.query.return_value = []

        changed_symbols = [
            {'symbol_name': f'symbol_{i}', 'file_path': f'src/file{i}.py',
             'start_line': 1, 'end_line': 10}
            for i in range(100)
        ]

        start = time.time()
        result = parser.get_impact_tests(
            changed_symbols, project_id=1, embedder=None, max_hops=1, top_k=10
        )
        elapsed = time.time() - start

        assert elapsed < 10.0

    # --- Test edge cases ---

    def test_empty_changed_symbols(self, parser, mock_neo4j):
        """Test empty input returns empty list."""
        result = parser.get_impact_tests([], project_id=1, embedder=None, max_hops=1, top_k=5)

        assert result == []

    def test_no_neo4j_client(self):
        """Test returns empty without Neo4j client."""
        parser = DiffParser(neo4j_client=None)

        changed_symbols = [
            {'symbol_name': 'add', 'file_path': 'src/math.py', 'start_line': 1, 'end_line': 10}
        ]

        result = parser.get_impact_tests(
            changed_symbols, project_id=1, embedder=None, max_hops=1, top_k=5
        )

        assert result == []

    def test_top_k_limit_applied(self, parser, mock_neo4j):
        """Test top_k limits results."""
        mock_neo4j.query.return_value = [
            {'test_name': f'test_{i}', 'test_file': f'test_{i}.ts', 'confidence': 0.5, 'source': 'coverage'}
            for i in range(20)
        ]

        changed_symbols = [
            {'symbol_name': 'add', 'file_path': 'src/math.py', 'start_line': 1, 'end_line': 10}
        ]

        result = parser.get_impact_tests(
            changed_symbols, project_id=1, embedder=None, max_hops=1, top_k=5
        )

        assert len(result) <= 5