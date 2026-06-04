import pytest
from unittest.mock import Mock, patch, MagicMock


class TestModelCompareInstantiation:
    """Test ModelCompare instantiation."""

    def test_default_instantiation(self):
        from testsquad_core.intelligence.model_compare import ModelCompare
        mock_neo4j = Mock()
        compare = ModelCompare(mock_neo4j)
        assert compare.neo4j is mock_neo4j
        assert compare.siamese_mapper is not None

    def test_custom_config(self):
        from testsquad_core.intelligence.model_compare import ModelCompare
        from testsquad_core.intelligence.siamese_config import SiameseConfig
        mock_neo4j = Mock()
        config = SiameseConfig(siamese_threshold=0.70)
        compare = ModelCompare(mock_neo4j, config=config)
        assert compare.config.siamese_threshold == 0.70


class TestModelCompareSymbol:
    """Test single symbol comparison."""

    def test_compare_symbol_structure(self):
        from testsquad_core.intelligence.model_compare import ModelCompare
        mock_neo4j = Mock()
        compare = ModelCompare(mock_neo4j)
        
        result = compare.compare_symbol(
            "test_func",
            "src/test.ts",
            project_id=1,
            top_k=3
        )
        
        assert "symbol" in result
        assert "siamese" in result
        assert "mpnet" in result
        assert "vector" in result

    def test_compare_symbol_empty(self):
        from testsquad_core.intelligence.model_compare import ModelCompare
        mock_neo4j = Mock()
        compare = ModelCompare(mock_neo4j)
        
        with patch.object(compare, '_match_with_siamese', return_value=[]):
            result = compare.compare_symbol("func", "src/func.ts", 1)
        
        assert result["siamese"] == []


class TestModelCompareProject:
    """Test project comparison."""

    def test_compare_project_structure(self):
        from testsquad_core.intelligence.model_compare import ModelCompare
        mock_neo4j = Mock()
        compare = ModelCompare(mock_neo4j)
        
        result = compare.compare_project(1)
        
        assert "project_id" in result
        assert "siamese_total" in result
        assert "vector_total" in result

    def test_compare_project_empty(self):
        from testsquad_core.intelligence.model_compare import ModelCompare
        mock_neo4j = Mock()
        compare = ModelCompare(mock_neo4j)
        
        with patch.object(compare.siamese_mapper, 'generate_candidates', return_value=[]):
            result = compare.compare_project(1)
        
        assert result["siamese_total"] == 0


class TestModelCompareOverlap:
    """Test overlap calculation."""

    def test_get_overlap_structure(self):
        from testsquad_core.intelligence.model_compare import ModelCompare
        mock_neo4j = Mock()
        compare = ModelCompare(mock_neo4j)
        
        result = compare.get_overlap(1)
        
        assert "project_id" in result
        assert "exact_match_count" in result
        assert "unique_to_siamese" in result
        assert "unique_to_vector" in result

    def test_get_overlap_empty(self):
        from testsquad_core.intelligence.model_compare import ModelCompare
        mock_neo4j = Mock()
        compare = ModelCompare(mock_neo4j)
        
        with patch.object(compare.siamese_mapper, 'generate_candidates', return_value=[]):
            with patch.object(compare, '_init_vector_mapper'):
                with patch.object(compare.vector_mapper, 'generate_candidates', return_value=[]):
                    result = compare.get_overlap(1)
        
        assert result["exact_match_count"] == 0


class TestModelCompareIntegration:
    """Test model comparison integration."""

    def test_uses_siamese_mapper(self):
        from testsquad_core.intelligence.model_compare import ModelCompare
        mock_neo4j = Mock()
        compare = ModelCompare(mock_neo4j)
        from testsquad_core.intelligence.siamese_mapper import SiameseMapper
        assert isinstance(compare.siamese_mapper, SiameseMapper)

    def test_uses_vector_mapper(self):
        from testsquad_core.intelligence.model_compare import ModelCompare
        mock_neo4j = Mock()
        compare = ModelCompare(mock_neo4j)
        compare._init_vector_mapper()
        from testsquad_core.intelligence.vector_mapper import VectorMapper
        assert isinstance(compare.vector_mapper, VectorMapper)