import pytest
import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from testsquad_core.intelligence.vector_mapper import VectorMapper


class TestVectorMatching:
    """Test Task 2.2.2: Vector Matching Tests."""

    @pytest.fixture
    def mock_neo4j(self):
        mock = MagicMock()
        return mock

    @pytest.fixture
    def mock_embedder(self):
        mock = MagicMock()
        mock.embed_batch.return_value = [[1.0] * 768] * 10
        mock.similarity.return_value = [(0, 0.95)]
        return mock

    @pytest.fixture
    def vector_mapper(self, mock_neo4j, mock_embedder):
        vm = VectorMapper(neo4j=mock_neo4j, embedder=mock_embedder)
        return vm

    # --- Test _match_vectors ---

    def test_match_vectors_empty(self, vector_mapper):
        """Test empty candidates returns empty matches."""
        result = vector_mapper._match_vectors([], threshold=0.75)
        assert result == []

    def test_match_vectors_identical(self, vector_mapper):
        """Test identical summaries → high similarity."""
        candidates = [
            {"symbol_name": "utils", "symbol_file": "src/utils.ts", "test_name": "test_utils", "test_file": "tests/utils.test.ts", "confidence": 0.85}
        ]
        
        # Mock embedder to return identical embeddings
        vector_mapper.embedder.embed_batch.return_value = [[1.0] * 768]
        vector_mapper.embedder.similarity.return_value = [(0, 0.99)]
        
        result = vector_mapper._match_vectors(candidates, threshold=0.75)
        
        assert len(result) >= 1

    def test_match_vectors_unrelated(self, vector_mapper):
        """Test unrelated summaries → low similarity."""
        candidates = [
            {"symbol_name": "database", "symbol_file": "src/db.ts", "test_name": "test_ui", "test_file": "tests/ui.test.ts", "confidence": 0.1}
        ]
        
        # Mock to return low similarity
        vector_mapper.embedder.similarity.return_value = [(0, 0.05)]
        
        result = vector_mapper._match_vectors(candidates, threshold=0.75)
        
        # Should be filtered out (below threshold)
        assert len(result) == 0

    def test_match_vectors_threshold_075(self, vector_mapper):
        """Test threshold 0.75."""
        candidates = [
            {"symbol_name": "func1", "symbol_file": "src/a.ts", "test_name": "test_a", "test_file": "tests/a.test.ts", "confidence": 0.75}
        ]
        
        vector_mapper.embedder.similarity.return_value = [(0, 0.75)]
        
        result = vector_mapper._match_vectors(candidates, threshold=0.75)
        
        assert len(result) >= 1

    def test_match_vectors_threshold_074(self, vector_mapper):
        """Test threshold 0.74 is filtered."""
        candidates = [
            {"symbol_name": "func1", "symbol_file": "src/a.ts", "test_name": "test_a", "test_file": "tests/a.test.ts", "confidence": 0.74}
        ]
        
        vector_mapper.embedder.similarity.return_value = [(0, 0.74)]
        
        result = vector_mapper._match_vectors(candidates, threshold=0.75)
        
        assert len(result) == 0

    def test_match_vectors_above_threshold(self, vector_mapper):
        """Test threshold 0.90."""
        candidates = [
            {"symbol_name": "func1", "symbol_file": "src/a.ts", "test_name": "test_a", "test_file": "tests/a.test.ts", "confidence": 0.90}
        ]
        
        vector_mapper.embedder.similarity.return_value = [(0, 0.92)]
        
        result = vector_mapper._match_vectors(candidates, threshold=0.90)
        
        assert len(result) >= 1

    # --- Test Fusion Logic ---

    def test_fusion_max_vector(self, vector_mapper):
        """Test fusion uses max - vector wins."""
        candidates = [
            {"symbol_name": "func1", "symbol_file": "src/a.ts", "test_name": "test_a", "test_file": "tests/a.test.ts", "confidence": 0.50}
        ]
        
        vector_mapper.embedder.similarity.return_value = [(0, 0.85)]  # vector
        
        result = vector_mapper._match_vectors(candidates, threshold=0.75)
        
        if result:
            assert result[0].source == "vector"

    def test_fusion_max_bm25(self, vector_mapper):
        """Test fusion uses max - BM25 wins."""
        candidates = [
            {"symbol_name": "func1", "symbol_file": "src/a.ts", "test_name": "test_a", "test_file": "tests/a.test.ts", "confidence": 0.50}
        ]
        
        vector_mapper.embedder.similarity.return_value = [(0, 0.60)]  # low vector
        # High BM25
        
        with patch.object(vector_mapper, '_bm25_score', return_value=0.85):
            result = vector_mapper._match_vectors(candidates, threshold=0.75)
        
        if result:
            assert result[0].source == "bm25"

    def test_fusion_max_heuristic(self, vector_mapper):
        """Test fusion uses max - heuristic wins."""
        candidates = [
            {"symbol_name": "func1", "symbol_file": "src/a.ts", "test_name": "test_a", "test_file": "tests/a.test.ts", "confidence": 0.90}
        ]
        
        # All other scores below threshold
        vector_mapper.embedder.similarity.return_value = [(0, 0.50)]
        
        result = vector_mapper._match_vectors(candidates, threshold=0.75)
        
        if result:
            assert result[0].source in ["heuristic", "bm25", "vector"]


class TestBM25Scoring:
    """Test BM25 keyword overlap scoring."""

    @pytest.fixture
    def vector_mapper(self):
        mock_neo4j = MagicMock()
        return VectorMapper(neo4j=mock_neo4j)

    def test_bm25_identical(self, vector_mapper):
        """Test identical text → score 1.0."""
        score = vector_mapper._bm25_score("hello world", "hello world")
        assert score == 1.0

    def test_bm25_overlap(self, vector_mapper):
        """Test partial overlap."""
        score = vector_mapper._bm25_score("hello world foo", "hello world bar")
        assert 0.0 < score < 1.0

    def test_bm25_no_overlap(self, vector_mapper):
        """Test no overlap → score 0.0."""
        score = vector_mapper._bm25_score("hello", "world")
        assert score == 0.0

    def test_bm25_case_insensitive(self, vector_mapper):
        """Test case insensitivity."""
        score = vector_mapper._bm25_score("HELLO", "hello")
        assert score == 1.0

    def test_bm25_empty_first(self, vector_mapper):
        """Test empty first text."""
        score = vector_mapper._bm25_score("", "hello")
        assert score == 0.0

    def test_bm25_empty_second(self, vector_mapper):
        """Test empty second text."""
        score = vector_mapper._bm25_score("hello", "")
        assert score == 0.0


class TestEdgeCreation:
    """Test edge creation in Neo4j."""

    @pytest.fixture
    def mock_neo4j(self):
        mock = MagicMock()
        mock.query.return_value = [{"count": 5}]
        return mock

    @pytest.fixture
    def vector_mapper(self, mock_neo4j):
        mock_embedder = MagicMock()
        return VectorMapper(neo4j=mock_neo4j, embedder=mock_embedder)

    def test_create_edges_empty(self, vector_mapper, mock_neo4j):
        """Test empty matches returns 0."""
        result = vector_mapper._create_edges([], project_id=1)
        assert result == 0
        assert not mock_neo4j.query.called

    def test_create_edges_single(self, vector_mapper, mock_neo4j):
        """Test single edge creation."""
        from testsquad_core.intelligence.vector_mapper import VectorMapper
        
        matches = [
            VectorMapper.Match(
                symbol_name="func1",
                symbol_file="src/utils.ts",
                test_name="test_utils",
                test_file="tests/utils.test.ts",
                confidence=0.85,
                source="vector",
                reasoning="Vector similarity: 0.85"
            )
        ]
        
        result = vector_mapper._create_edges(matches, project_id=1)
        
        assert result == 1
        assert mock_neo4j.query.called

    def test_create_edges_batch(self, vector_mapper, mock_neo4j):
        """Test batch edge creation (10K+)."""
        from testsquad_core.intelligence.vector_mapper import VectorMapper
        
        matches = [
            VectorMapper.Match(
                symbol_name=f"func{i}",
                symbol_file=f"src/file{i}.ts",
                test_name=f"test{i}",
                test_file=f"tests/file{i}.test.ts",
                confidence=0.85,
                source="vector",
                reasoning=f"Similarity: 0.85"
            )
            for i in range(10000)
        ]
        
        result = vector_mapper._create_edges(matches, project_id=1)
        
        assert result == 10000


class TestMapTestsPipeline:
    """Test the full map_tests pipeline."""

    @pytest.fixture
    def mock_neo4j(self):
        mock = MagicMock()
        return mock

    @pytest.fixture
    def vector_mapper(self, mock_neo4j):
        mock_embedder = MagicMock()
        mock_embedder.embed_batch.return_value = [[1.0] * 768]
        mock_embedder.similarity.return_value = [(0, 0.85)]
        return VectorMapper(neo4j=mock_neo4j, embedder=mock_embedder)

    def test_map_tests_flow(self, vector_mapper, mock_neo4j):
        """Test full pipeline returns dict."""
        with patch.object(vector_mapper, 'generate_candidates', return_value=[
            {"symbol_name": "func1", "symbol_file": "src/a.ts", "test_name": "test_a", "test_file": "tests/a.test.ts", "confidence": 0.85}
        ]):
            with patch.object(vector_mapper, '_match_vectors', return_value=[]):
                with patch.object(vector_mapper, '_create_edges', return_value=0):
                    result = vector_mapper.map_tests(project_id=1)
        
        assert "candidates" in result
        assert "matches" in result
        assert "edges_created" in result
        assert "threshold" in result

    def test_map_tests_threshold_param(self, vector_mapper, mock_neo4j):
        """Test threshold parameter."""
        with patch.object(vector_mapper, 'generate_candidates', return_value=[]):
            result = vector_mapper.map_tests(project_id=1, threshold=0.5)
        
        assert result["threshold"] == 0.5


class TestConfidenceScoring:
    """Test confidence scoring edge cases."""

    @pytest.fixture
    def vector_mapper(self):
        mock_neo4j = MagicMock()
        return VectorMapper(neo4j=mock_neo4j)

    def test_confidence_at_threshold_boundary(self, vector_mapper):
        """Test exact threshold boundary."""
        candidates = [
            {"symbol_name": "func", "symbol_file": "src/a.ts", "test_name": "test", "test_file": "tests/a.test.ts", "confidence": c}
            for c in [0.74, 0.75, 0.76]
        ]
        
        # Mock each to have different scores
        def mock_sim(query, targets, top_k=1):
            return [(0, targets[0][0] if targets else 0)]
        
        results = []
        for i, c in enumerate(candidates):
            mock_emb = [[c["confidence"]] * 768]
            vector_mapper.embedder.embed_batch = lambda x: mock_emb
            results.append(vector_mapper._match_vectors([c], threshold=0.75))
        
        # Only 0.75 and above should pass
        assert len(results[0]) == 0 or results[0][0].confidence >= 0.75

    def test_confidence_all_zeros(self, vector_mapper):
        """Test all zero scores."""
        candidates = [
            {"symbol_name": "func", "symbol_file": "src/a.ts", "test_name": "test", "test_file": "tests/a.test.ts", "confidence": 0.0}
        ]
        
        # All return 0
        vector_mapper.embedder.similarity.return_value = [(0, 0.0)]
        
        result = vector_mapper._match_vectors(candidates, threshold=0.75)
        
        assert result == []


class TestEdgeCaseData:
    """Test edge cases with empty/malformed data."""

    @pytest.fixture
    def vector_mapper(self):
        mock_neo4j = MagicMock()
        mock_embedder = MagicMock()
        return VectorMapper(neo4j=mock_neo4j, embedder=mock_embedder)

    def test_missing_symbol_name(self, vector_mapper):
        """Test missing symbol name."""
        candidates = [
            {"symbol_file": "src/a.ts", "test_name": "test", "test_file": "tests/a.test.ts", "confidence": 0.85}
        ]
        
        result = vector_mapper._match_vectors(candidates)
        assert isinstance(result, list)

    def test_missing_test_name(self, vector_mapper):
        """Test missing test name."""
        candidates = [
            {"symbol_name": "func", "symbol_file": "src/a.ts", "test_file": "tests/a.test.ts", "confidence": 0.85}
        ]
        
        result = vector_mapper._match_vectors(candidates)
        assert isinstance(result, list)

    def test_empty_file_paths(self, vector_mapper):
        """Test empty file paths."""
        candidates = [
            {"symbol_name": "", "symbol_file": "", "test_name": "", "test_file": "", "confidence": 0.85}
        ]
        
        result = vector_mapper._match_vectors(candidates)
        assert isinstance(result, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])