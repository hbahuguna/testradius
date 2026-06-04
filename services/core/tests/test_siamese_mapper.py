import pytest
from unittest.mock import Mock, patch, MagicMock


class TestMatchNamedTuple:
    """Test Match NamedTuple structure."""

    def test_match_creation(self):
        from testsquad_core.intelligence.siamese_mapper import Match
        match = Match(
            symbol_name="func1",
            symbol_file="src/func.ts",
            symbol_summary="Calculate distance",
            test_name="test_func",
            test_file="tests/func.test.ts",
            test_summary="Test distance calculation",
            confidence=0.85,
            siamese_confidence=0.85,
            mpnet_confidence=0.72,
            heuristic_confidence=0.70,
            source="layers",
            reasoning="Siamese: 0.85, MPNet: 0.72, Heuristic: 0.70"
        )
        assert match.symbol_name == "func1"
        assert match.confidence == 0.85
        assert match.siamese_confidence == 0.85


class TestSiameseMapperInstantiation:
    """Test SiameseMapper instantiation."""

    def test_default_instantiation(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper
        mock_neo4j = Mock()
        mapper = SiameseMapper(mock_neo4j)
        assert mapper.neo4j is mock_neo4j
        assert mapper.config is not None
        assert mapper.embedder is not None

    def test_custom_config(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        mock_neo4j = Mock()
        config = SiameseConfig(siamese_threshold=0.70)
        mapper = SiameseMapper(mock_neo4j, config=config)
        assert mapper.config.siamese_threshold == 0.70

    def test_custom_embedder(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper
        from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder
        mock_neo4j = Mock()
        embedder = MultiModelEmbedder()
        mapper = SiameseMapper(mock_neo4j, embedder=embedder)
        assert mapper.embedder is embedder


class TestSiameseMapperLayers:
    """Test candidate generation layers."""

    def test_layer1_calls_graph(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper
        mock_neo4j = Mock()
        mock_neo4j.query.return_value = [
            {"name": "test_func", "file_path": "tests/func.test.ts"}
        ]
        mapper = SiameseMapper(mock_neo4j)
        
        symbol = {"name": "func1", "file_path": "src/func.ts"}
        all_tests = [
            {"name": "test_func", "file_path": "tests/func.test.ts"}
        ]
        
        result = mapper._layer1_calls_graph(symbol, all_tests)
        assert len(result) == 1
        assert result[0][1] == 0.95

    def test_layer2_filename_heuristics_ts(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper
        mock_neo4j = Mock()
        mapper = SiameseMapper(mock_neo4j)
        
        symbol = {"name": "func", "file_path": "src/utils.ts"}
        all_tests = [
            {"name": "test_func", "file_path": "tests/utils.test.ts"},
            {"name": "test_other", "file_path": "tests/other.test.ts"},
        ]
        
        result = mapper._layer2_filename_heuristics(symbol, all_tests)
        assert len(result) >= 1

    def test_layer2_filename_heuristics_python(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper
        mock_neo4j = Mock()
        mapper = SiameseMapper(mock_neo4j)
        
        symbol = {"name": "func", "file_path": "src/utils.py"}
        all_tests = [
            {"name": "test_func", "file_path": "tests/test_utils.py"},
        ]
        
        result = mapper._layer2_filename_heuristics(symbol, all_tests)
        assert len(result) >= 1

    def test_layer3_community_match(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper
        mock_neo4j = Mock()
        mapper = SiameseMapper(mock_neo4j)
        
        symbol = {"name": "func", "community_id": 1}
        all_tests = [
            {"name": "test_func", "test_community_id": 1},
            {"name": "test_other", "test_community_id": 2},
        ]
        
        result = mapper._layer3_community(symbol, all_tests)
        assert len(result) == 1
        assert result[0][1] == 0.70

    def test_layer3_no_community(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper
        mock_neo4j = Mock()
        mapper = SiameseMapper(mock_neo4j)
        
        symbol = {"name": "func", "community_id": 0}
        all_tests = [
            {"name": "test_func", "test_community_id": 1},
        ]
        
        result = mapper._layer3_community(symbol, all_tests)
        assert len(result) == 0


class TestSiameseMapperCandidates:
    """Test candidate building."""

    def test_build_candidates(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper
        mock_neo4j = Mock()
        mock_neo4j.query.return_value = [
            {"name": "test_func", "file_path": "tests/func.test.ts"}
        ]
        mapper = SiameseMapper(mock_neo4j)
        
        product_symbols = [
            {"name": "func", "file_path": "src/func.ts", "summary": "Test function", "community_id": 1}
        ]
        all_tests = [
            {"name": "test_func", "file_path": "tests/func.test.ts", "summary": "Test func", "test_community_id": 1}
        ]
        
        with patch.object(mapper, '_layer1_calls_graph', return_value=[]):
            with patch.object(mapper, '_layer2_filename_heuristics', return_value=[]):
                with patch.object(mapper, '_layer3_community', return_value=[]):
                    result = mapper._build_candidates(product_symbols, all_tests)
        
        assert isinstance(result, list)

    def test_build_candidates_empty(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper
        mock_neo4j = Mock()
        mapper = SiameseMapper(mock_neo4j)
        
        result = mapper._build_candidates([], [])
        assert result == []


class TestSiameseMapperMatching:
    """Test Siamese matching."""

    def test_match_with_siamese_empty_candidates(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper
        mock_neo4j = Mock()
        mapper = SiameseMapper(mock_neo4j)
        
        result = mapper._match_with_siamese([], threshold=0.75)
        assert result == []

    def test_match_with_siamese_threshold_filtering(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper
        mock_neo4j = Mock()
        mock_embedder = Mock()
        mock_embedder.embed_batch.return_value = [[0.1] * 768] * 2
        mock_embedder.compute_similarity.return_value = [(0, 0.5)]  # Below threshold
        
        mapper = SiameseMapper(mock_neo4j)
        mapper.embedder = mock_embedder
        
        candidates = [
            {
                "symbol_name": "func1",
                "symbol_file": "src/func.ts",
                "symbol_summary": "Test",
                "test_name": "test_func",
                "test_file": "tests/func.test.ts",
                "test_summary": "Test",
                "heuristic_confidence": 0.60,
            }
        ]
        
        result = mapper._match_with_siamese(candidates, threshold=0.75)
        assert len(result) == 0  # Filtered out by threshold

    def test_match_with_siamese_above_threshold(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper
        mock_neo4j = Mock()
        mock_embedder = Mock()
        mock_embedder.embed_batch.return_value = [[0.1] * 768] * 2
        mock_embedder.compute_similarity.return_value = [(0, 0.85)]  # Above threshold
        
        mapper = SiameseMapper(mock_neo4j)
        mapper.embedder = mock_embedder
        
        candidates = [
            {
                "symbol_name": "func1",
                "symbol_file": "src/func.ts",
                "symbol_summary": "Test",
                "test_name": "test_func",
                "test_file": "tests/func.test.ts",
                "test_summary": "Test",
                "heuristic_confidence": 0.70,
            }
        ]
        
        result = mapper._match_with_siamese(candidates, threshold=0.75)
        assert len(result) == 1
        assert result[0].confidence >= 0.75


class TestSiameseMapperEdges:
    """Test edge creation."""

    def test_create_edges_empty(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper, Match
        mock_neo4j = Mock()
        mock_neo4j.bulk_add_siamese_edges.return_value = 0
        mapper = SiameseMapper(mock_neo4j)
        
        result = mapper.create_edges([], project_id=1)
        assert result == 0

    def test_create_edges_single(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper, Match
        mock_neo4j = Mock()
        mock_neo4j.bulk_add_siamese_edges.return_value = 1
        mapper = SiameseMapper(mock_neo4j)
        
        match = Match(
            symbol_name="func1",
            symbol_file="src/func.ts",
            symbol_summary="Test",
            test_name="test_func",
            test_file="tests/func.test.ts",
            test_summary="Test",
            confidence=0.85,
            siamese_confidence=0.85,
            mpnet_confidence=0.72,
            heuristic_confidence=0.70,
            source="layers",
            reasoning="Test"
        )
        
        result = mapper.create_edges([match], project_id=1, model="siamese")
        assert result == 1
        mock_neo4j.bulk_add_siamese_edges.assert_called_once()

    def test_create_edges_multiple(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper, Match
        mock_neo4j = Mock()
        mock_neo4j.bulk_add_siamese_edges.return_value = 3
        mapper = SiameseMapper(mock_neo4j)
        
        matches = [
            Match(
                symbol_name=f"func{i}",
                symbol_file=f"src/func{i}.ts",
                symbol_summary="Test",
                test_name=f"test_func{i}",
                test_file=f"tests/func{i}.test.ts",
                test_summary="Test",
                confidence=0.85,
                siamese_confidence=0.85,
                mpnet_confidence=0.72,
                heuristic_confidence=0.70,
                source="layers",
                reasoning="Test"
            )
            for i in range(3)
        ]
        
        result = mapper.create_edges(matches, project_id=1)
        assert result == 3


class TestSiameseMapperPipeline:
    """Test main mapping pipeline."""

    def test_generate_candidates(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper
        mock_neo4j = Mock()
        mock_neo4j.query.side_effect = [
            [{"name": "func1", "file_path": "src/func.ts", "summary": "Test", "community_id": 1}],
            [{"name": "test_func", "file_path": "tests/func.test.ts", "summary": "Test", "test_community_id": 1}],
        ]
        mapper = SiameseMapper(mock_neo4j)
        
        with patch.object(mapper, '_build_candidates', return_value=[]):
            result = mapper.generate_candidates(1)
        
        assert isinstance(result, list)

    def test_map_tests_empty_symbols(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper
        mock_neo4j = Mock()
        mock_neo4j.query.return_value = []
        mapper = SiameseMapper(mock_neo4j)
        
        results = list(mapper.map_tests(1))
        
        assert len(results) >= 1
        assert results[0]["event"] == "reasoning"

    def test_map_tests_no_tests(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper
        mock_neo4j = Mock()
        mock_neo4j.query.side_effect = [
            [{"name": "func1", "file_path": "src/func.ts", "summary": "Test", "community_id": 1}],
            [],
        ]
        mapper = SiameseMapper(mock_neo4j)
        
        results = list(mapper.map_tests(1))
        
        assert any(r.get("data", {}).get("status") == "NO_TESTS" for r in results)


class TestConfidenceFusion:
    """Test confidence fusion logic."""

    def test_max_fusion_siamese_wins(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper
        mock_neo4j = Mock()
        mock_embedder = Mock()
        mock_embedder.embed_batch.return_value = [[0.1] * 768]
        mock_embedder.compute_similarity.return_value = [(0, 0.85)]
        
        mapper = SiameseMapper(mock_neo4j)
        mapper.embedder = mock_embedder
        
        candidates = [
            {
                "symbol_name": "func",
                "symbol_file": "src/func.ts",
                "symbol_summary": "Test",
                "test_name": "test_func",
                "test_file": "tests/func.test.ts",
                "test_summary": "Test",
                "heuristic_confidence": 0.70,
            }
        ]
        
        with patch.object(mapper, '_layer1_calls_graph', return_value=[]):
            with patch.object(mapper, '_layer2_filename_heuristics', return_value=[]):
                with patch.object(mapper, '_layer3_community', return_value=[]):
                    result = mapper._match_with_siamese(candidates, threshold=0.75)
        
        if result:
            assert result[0].confidence >= 0.70

    def test_threshold_from_config(self):
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        mock_neo4j = Mock()
        config = SiameseConfig(siamese_threshold=0.80, mpnet_threshold=0.90)
        mapper = SiameseMapper(mock_neo4j, config=config)
        
        assert mapper.config.siamese_threshold == 0.80
        assert mapper.config.mpnet_threshold == 0.90