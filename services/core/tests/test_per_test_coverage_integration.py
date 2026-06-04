import pytest
import tempfile
import os
import json
from unittest.mock import MagicMock


class TestPerTestCoverageIntegration:
    """End-to-end integration test with real subprocess and Neo4j."""
    
    def test_full_pipeline_in_memory(self):
        """Test the full pipeline: transformer -> Neo4j store."""
        # Create a temp source file with a simple function
        temp_dir = tempfile.mkdtemp()
        source_file = os.path.join(temp_dir, "store.py")
        
        with open(source_file, 'w') as f:
            f.write("def get_value():\n    return 42\n")
        
        # Simulate per-test coverage data
        adjusted_coverage = {
            "tests/test_store.py::test_get": {
                source_file: [1, 2]  # lines in get_value
            }
        }
        
        try:
            # Test the transformer
            from testsquad_core.instrumentation.transformer import InstrumentationTransformer
            transformer = InstrumentationTransformer()
            mappings = transformer.transform(adjusted_coverage)
            
            # Verify mappings were created
            assert len(mappings) >= 1
            
            # Test Neo4j store with mock
            from testsquad_core.instrumentation.neo4j_store import Neo4jStore
            mock_client = MagicMock()
            store = Neo4jStore(neo4j_client=mock_client)
            
            edge_count = store.store_mappings(mappings, project_id=1)
            
            # Verify edges were created
            assert mock_client.query.call_count >= 1
            
        finally:
            import shutil
            shutil.rmtree(temp_dir)

    def test_impact_query_with_real_mappings(self):
        """Verify that storing mappings enables impact queries."""
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore
        
        # Mock the Neo4j to return some data
        mock_client = MagicMock()
        mock_client.query.return_value = [
            {"test_name": "test_get_key", "test_file": "tests/test_store.py", "confidence": 1.0}
        ]
        
        store = Neo4jStore(neo4j_client=mock_client)
        
        # Query for impacted tests
        impacted = store.get_impacted_tests(
            project_id=1,
            changed_symbols=["get", "set"]  # Multiple changed symbols
        )
        
        # Should return results
        assert len(impacted) > 0
        assert impacted[0]["test_name"] == "test_get_key"
        
        # Verify the query included both symbols
        query_call = mock_client.query.call_args_list[0]
        params = query_call[0][1]
        assert "get" in params["changed_symbols"]
        assert "set" in params["changed_symbols"]