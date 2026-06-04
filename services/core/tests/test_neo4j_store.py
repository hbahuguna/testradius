import pytest
from unittest.mock import MagicMock, call
from testsquad_core.instrumentation.symbol_resolver import Symbol


class TestNeo4jStore:
    """Tests for Neo4jStore - persists test-symbol edges in Neo4j."""

    def test_create_tests_relationship_edges(self):
        """Creates (:TestSymbol)-[:TESTS]->(:Symbol) edges with correct properties."""
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore
        
        mock_client = MagicMock()
        store = Neo4jStore(neo4j_client=mock_client)
        
        # Create test data
        test_mappings = [
            {
                "test_name": "test_add",
                "test_file": "tests/test_math.py",
                "symbols": [
                    Symbol(name="add", symbol_type="function", file_path="src/math.py", start_line=1, end_line=10)
                ]
            }
        ]
        
        store.store_mappings(test_mappings, project_id=1)
        
        # Verify the query was called with correct params
        mock_client.query.assert_called()
        call_args = mock_client.query.call_args_list[0]
        query = call_args[0][0]
        
        # Verify it uses [:EVIDENCE] relationship
        assert "EVIDENCE" in query
        assert "source: 'coverage'" in query
        assert "confidence: 1.0" in query

    def test_impact_query_returns_tests_for_symbol(self):
        """Querying by symbol name returns associated tests."""
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore
        
        mock_client = MagicMock()
        mock_client.query.return_value = [
            {"test_name": "test_add", "test_file": "tests/test_math.py", "confidence": 1.0}
        ]
        
        store = Neo4jStore(neo4j_client=mock_client)
        impacted = store.get_impacted_tests(project_id=1, changed_symbols=["add"])
        
        assert len(impacted) == 1
        assert impacted[0]["test_name"] == "test_add"
        
        # Verify the query uses [:EVIDENCE] relationship
        mock_client.query.assert_called()
        call_args = mock_client.query.call_args_list[0]
        query = call_args[0][0]
        assert "EVIDENCE" in query

    def test_empty_mappings_no_queries(self):
        """Empty mappings list doesn't execute any queries."""
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore
        
        mock_client = MagicMock()
        store = Neo4jStore(neo4j_client=mock_client)
        
        store.store_mappings([], project_id=1)
        
        # No queries should be made
        mock_client.query.assert_not_called()

    def test_multiple_symbols_per_test(self):
        """A test covering multiple symbols creates multiple edges."""
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore
        
        mock_client = MagicMock()
        store = Neo4jStore(neo4j_client=mock_client)
        
        test_mappings = [
            {
                "test_name": "test_math_ops",
                "test_file": "tests/test_math.py",
                "symbols": [
                    Symbol(name="add", symbol_type="function", file_path="src/math.py", start_line=1, end_line=10),
                    Symbol(name="subtract", symbol_type="function", file_path="src/math.py", start_line=12, end_line=20)
                ]
            }
        ]
        
        store.store_mappings(test_mappings, project_id=1)
        
        # Should have created 2 edges for 2 symbols
        assert mock_client.query.call_count == 2

    def test_no_neo4j_client_graceful_handling(self):
        """No Neo4j client returns empty results without error."""
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore
        
        store = Neo4jStore(neo4j_client=None)
        
        # Should not raise
        impacted = store.get_impacted_tests(project_id=1, changed_symbols=["add"])
        assert impacted == []
        
        result = store.store_mappings([], project_id=1)
        assert result == 0