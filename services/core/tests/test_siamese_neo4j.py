import pytest
from unittest.mock import Mock, patch, MagicMock


class TestBulkAddSiameseEdges:
    """Test bulk_add_siamese_edges method."""

    def test_empty_edges_returns_zero(self):
        from testsquad_core.graph.client import Neo4jClient
        client = Neo4jClient()
        with patch.object(client, 'query', return_value=[{"edge_count": 0}]):
            result = client.bulk_add_siamese_edges([])
            assert result == 0

    def test_single_edge(self):
        from testsquad_core.graph.client import Neo4jClient
        client = Neo4jClient()
        
        edges = [{
            "symbol_name": "calculateDistance3D",
            "symbol_file": "src/math.ts",
            "test_name": "should calculate distance",
            "test_file": "tests/math.test.ts",
            "siamese_confidence": 0.85,
            "mpnet_confidence": 0.72,
            "heuristic_confidence": 0.70,
            "final_confidence": 0.85,
            "reasoning": "Siamese: 0.85, MPNet: 0.72, Heuristic: 0.70"
        }]
        
        with patch.object(client, 'query') as mock_query:
            mock_query.return_value = [{"edge_count": 1}]
            result = client.bulk_add_siamese_edges(edges, model="siamese")
            
            assert result == 1
            mock_query.assert_called_once()
            call_args = mock_query.call_args
            assert "siamese_confidence" in str(call_args)

    def test_multiple_edges(self):
        from testsquad_core.graph.client import Neo4jClient
        client = Neo4jClient()
        
        edges = [
            {"symbol_name": "func1", "symbol_file": "a.ts", "test_name": "t1", "test_file": "t.ts", "siamese_confidence": 0.8},
            {"symbol_name": "func2", "symbol_file": "b.ts", "test_name": "t2", "test_file": "t.ts", "siamese_confidence": 0.7},
            {"symbol_name": "func3", "symbol_file": "c.ts", "test_name": "t3", "test_file": "t.ts", "siamese_confidence": 0.9},
        ]
        
        with patch.object(client, 'query', return_value=[{"edge_count": 3}]):
            result = client.bulk_add_siamese_edges(edges)
            assert result == 3

    def test_default_model_is_siamese(self):
        from testsquad_core.graph.client import Neo4jClient
        client = Neo4jClient()
        
        edges = [{"symbol_name": "f", "symbol_file": "a.ts", "test_name": "t", "test_file": "t.ts"}]
        
        with patch.object(client, 'query') as mock_query:
            mock_query.return_value = [{"edge_count": 1}]
            client.bulk_add_siamese_edges(edges)
            
            call_args = str(mock_query.call_args)
            assert "siamese" in call_args

    def test_mpnet_model(self):
        from testsquad_core.graph.client import Neo4jClient
        client = Neo4jClient()
        
        edges = [{"symbol_name": "f", "symbol_file": "a.ts", "test_name": "t", "test_file": "t.ts"}]
        
        with patch.object(client, 'query') as mock_query:
            mock_query.return_value = [{"edge_count": 1}]
            client.bulk_add_siamese_edges(edges, model="mpnet")
            
            call_args = str(mock_query.call_args)
            assert "mpnet" in call_args

    def test_ensemble_model(self):
        from testsquad_core.graph.client import Neo4jClient
        client = Neo4jClient()
        
        edges = [{"symbol_name": "f", "symbol_file": "a.ts", "test_name": "t", "test_file": "t.ts"}]
        
        with patch.object(client, 'query') as mock_query:
            mock_query.return_value = [{"edge_count": 1}]
            client.bulk_add_siamese_edges(edges, model="ensemble")
            
            call_args = str(mock_query.call_args)
            assert "ensemble" in call_args


class TestGetMappingsByModel:
    """Test get_mappings_by_model method."""

    def test_get_siamese_mappings(self):
        from testsquad_core.graph.client import Neo4jClient
        client = Neo4jClient()
        
        with patch.object(client, 'query') as mock_query:
            mock_query.return_value = [
                {"symbol_name": "func1", "symbol_file": "a.ts", "test_name": "test1", "test_file": "t.ts", "siamese_confidence": 0.8},
            ]
            result = client.get_mappings_by_model(1, "siamese")
            
            assert len(result) == 1
            assert result[0]["symbol_name"] == "func1"
            mock_query.assert_called_once()

    def test_get_mpnet_mappings(self):
        from testsquad_core.graph.client import Neo4jClient
        client = Neo4jClient()
        
        with patch.object(client, 'query', return_value=[]):
            result = client.get_mappings_by_model(1, "mpnet")
            assert result == []

    def test_empty_project(self):
        from testsquad_core.graph.client import Neo4jClient
        client = Neo4jClient()
        
        with patch.object(client, 'query', return_value=[]):
            result = client.get_mappings_by_model(999, "siamese")
            assert result == []


class TestCompareModelMappings:
    """Test compare_model_mappings method."""

    def test_compare_returns_counts(self):
        from testsquad_core.graph.client import Neo4jClient
        client = Neo4jClient()
        
        with patch.object(client, 'query') as mock_query:
            mock_query.return_value = [
                {"model": "siamese", "count": 150},
                {"model": "mpnet", "count": 145},
                {"model": "ensemble", "count": 5},
            ]
            result = client.compare_model_mappings(1)
            
            assert result["siamese"] == 150
            assert result["mpnet"] == 145
            assert result["ensemble"] == 5

    def test_compare_with_missing_models(self):
        from testsquad_core.graph.client import Neo4jClient
        client = Neo4jClient()
        
        with patch.object(client, 'query') as mock_query:
            mock_query.return_value = [
                {"model": "siamese", "count": 100},
            ]
            result = client.compare_model_mappings(1)
            
            assert result["siamese"] == 100
            assert result["mpnet"] == 0
            assert result["ensemble"] == 0

    def test_compare_empty_project(self):
        from testsquad_core.graph.client import Neo4jClient
        client = Neo4jClient()
        
        with patch.object(client, 'query', return_value=[]):
            result = client.compare_model_mappings(999)
            
            assert result["siamese"] == 0
            assert result["mpnet"] == 0
            assert result["ensemble"] == 0


class TestSiameseEdgeProperties:
    """Test that edge properties are correctly set."""

    def test_all_confidence_scores_stored(self):
        from testsquad_core.graph.client import Neo4jClient
        client = Neo4jClient()
        
        edges = [{
            "symbol_name": "test_func",
            "symbol_file": "src/test.ts",
            "test_name": "test_test",
            "test_file": "tests/test.test.ts",
            "siamese_confidence": 0.85,
            "mpnet_confidence": 0.72,
            "heuristic_confidence": 0.70,
            "final_confidence": 0.85,
            "reasoning": "Max fusion: Siamese=0.85, MPNet=0.72, Heuristic=0.70"
        }]
        
        with patch.object(client, 'query') as mock_query:
            mock_query.return_value = [{"edge_count": 1}]
            client.bulk_add_siamese_edges(edges)
            
            call_args = str(mock_query.call_args)
            assert "siamese_confidence" in call_args
            assert "mpnet_confidence" in call_args
            assert "heuristic_confidence" in call_args
            assert "final_confidence" in call_args
            assert "reasoning" in call_args

    def test_default_confidence_values(self):
        from testsquad_core.graph.client import Neo4jClient
        client = Neo4jClient()
        
        edges = [{
            "symbol_name": "func",
            "symbol_file": "a.ts",
            "test_name": "test",
            "test_file": "t.ts"
        }]
        
        with patch.object(client, 'query') as mock_query:
            mock_query.return_value = [{"edge_count": 1}]
            client.bulk_add_siamese_edges(edges)
            
            call_args = str(mock_query.call_args)
            # Default confidence should be 0.0
            assert "0.0" in call_args


class TestQueryStructure:
    """Test query structure and parameters."""

    def test_query_uses_unwind(self):
        from testsquad_core.graph.client import Neo4jClient
        client = Neo4jClient()
        
        edges = [{"symbol_name": "f", "symbol_file": "a.ts", "test_name": "t", "test_file": "t.ts"}]
        
        with patch.object(client, 'query') as mock_query:
            mock_query.return_value = [{"edge_count": 1}]
            client.bulk_add_siamese_edges(edges)
            
            call_args = str(mock_query.call_args)
            assert "UNWIND" in call_args

    def test_query_uses_merges(self):
        from testsquad_core.graph.client import Neo4jClient
        client = Neo4jClient()
        
        edges = [{"symbol_name": "f", "symbol_file": "a.ts", "test_name": "t", "test_file": "t.ts"}]
        
        with patch.object(client, 'query') as mock_query:
            mock_query.return_value = [{"edge_count": 1}]
            client.bulk_add_siamese_edges(edges)
            
            call_args = str(mock_query.call_args)
            assert "MERGE" in call_args

    def test_query_sets_all_properties(self):
        from testsquad_core.graph.client import Neo4jClient
        client = Neo4jClient()
        
        edges = [{"symbol_name": "f", "symbol_file": "a.ts", "test_name": "t", "test_file": "t.ts", "siamese_confidence": 0.8}]
        
        with patch.object(client, 'query') as mock_query:
            mock_query.return_value = [{"edge_count": 1}]
            client.bulk_add_siamese_edges(edges)
            
            call_args = str(mock_query.call_args)
            # SET clause should set all properties
            for prop in ["siamese_confidence", "mpnet_confidence", "final_confidence", "model", "reasoning"]:
                assert prop in call_args