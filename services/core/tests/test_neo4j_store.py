import pytest
from unittest.mock import MagicMock, call
from testsquad_core.instrumentation.symbol_resolver import Symbol


class TestNeo4jStore:
    """Tests for Neo4jStore - persists test-symbol edges in Neo4j."""

    def test_create_tests_relationship_edges(self):
        """Creates (:TestSymbol)-[:EVIDENCE]->(:Symbol) edges with correct properties."""
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore
        
        mock_client = MagicMock()
        # Transaction returns [write_results, verify_results]; stored == expected.
        mock_client.run_in_transaction.return_value = [[{"created": 1}], [{"stored": 1}]]
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
        
        count = store.store_mappings(test_mappings, project_id=1)
        assert count == 1
        
        # Verify the write ran inside a single transaction
        mock_client.run_in_transaction.assert_called_once()
        statements = mock_client.run_in_transaction.call_args[0][0]
        query = statements[0][0]
        
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
        mock_client.run_in_transaction.assert_not_called()

    def test_multiple_symbols_per_test(self):
        """A test covering multiple symbols creates multiple edges."""
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore
        
        mock_client = MagicMock()
        mock_client.run_in_transaction.return_value = [[{"created": 2}], [{"stored": 2}]]
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
        
        count = store.store_mappings(test_mappings, project_id=1)
        
        # Should have created 2 edges for 2 symbols in one transaction
        assert count == 2
        statements = mock_client.run_in_transaction.call_args[0][0]
        assert len(statements[0][1]["edges"]) == 2

    def test_no_neo4j_client_graceful_handling(self):
        """No Neo4j client returns empty results without error."""
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore
        
        store = Neo4jStore(neo4j_client=None)
        
        # Should not raise
        impacted = store.get_impacted_tests(project_id=1, changed_symbols=["add"])
        assert impacted == []
        
        result = store.store_mappings([], project_id=1)
        assert result == 0

    def test_store_mappings_does_not_delete(self):
        """Merge semantics (store_mappings) must not remove existing evidence."""
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore

        mock_client = MagicMock()
        mock_client.run_in_transaction.return_value = [[{"created": 1}], [{"stored": 1}]]
        store = Neo4jStore(neo4j_client=mock_client)

        store.store_mappings([{
            "test_name": "t",
            "test_file": "tests/t.py",
            "symbols": [Symbol(name="add", symbol_type="function",
                               file_path="src/math.py", start_line=1, end_line=10)],
        }], project_id=1)

        statements = mock_client.run_in_transaction.call_args[0][0]
        assert all("DELETE" not in (s[0] or "").upper() for s in statements)

    def test_replace_mappings_deletes_before_write(self):
        """replace_mappings removes prior coverage evidence, then writes atomically."""
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore

        mock_client = MagicMock()
        mock_client.run_in_transaction.return_value = [
            [{"removed": 1}], [{"cleared": 1}], [{"created": 1}], [{"stored": 1}],
        ]
        store = Neo4jStore(neo4j_client=mock_client)

        count = store.replace_mappings([{
            "test_name": "t",
            "test_file": "tests/t.py",
            "symbols": [Symbol(name="add", symbol_type="function",
                               file_path="src/math.py", start_line=1, end_line=10)],
        }], project_id=1, built_at_sha="a" * 40)

        assert count == 1
        statements = mock_client.run_in_transaction.call_args[0][0]
        assert "DELETE" in statements[0][0].upper()
        assert "EVIDENCE" in statements[-1][0]  # verify query last
        assert mock_client.run_in_transaction.call_args[1].get("verify") is not None

    def test_same_named_methods_in_one_file_yield_two_edges(self):
        """Two methods sharing a bare name but with different spans stay distinct."""
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore

        mock_client = MagicMock()
        mock_client.run_in_transaction.return_value = [[{"created": 2}], [{"stored": 2}]]
        store = Neo4jStore(neo4j_client=mock_client)

        test_mappings = [{
            "test_name": "test_get",
            "test_file": "tests/test_m.py",
            "symbols": [
                Symbol(name="get", symbol_type="function", file_path="src/m.py", start_line=2, end_line=3),
                Symbol(name="get", symbol_type="function", file_path="src/m.py", start_line=7, end_line=8),
            ],
        }]

        count = store.store_mappings(test_mappings, project_id=1)

        assert count == 2
        edges = mock_client.run_in_transaction.call_args[0][0][0][1]["edges"]
        assert len(edges) == 2

    def test_symbol_node_identity_includes_line_span(self):
        """The Symbol MERGE key carries the line span so same-name symbols differ."""
        from testsquad_core.instrumentation.neo4j_store import Neo4jStore

        mock_client = MagicMock()
        mock_client.run_in_transaction.return_value = [[{"created": 1}], [{"stored": 1}]]
        store = Neo4jStore(neo4j_client=mock_client)

        store.store_mappings([{
            "test_name": "t",
            "test_file": "tests/t.py",
            "symbols": [Symbol(name="add", symbol_type="function",
                               file_path="src/math.py", start_line=1, end_line=10)],
        }], project_id=1)

        write_query = mock_client.run_in_transaction.call_args[0][0][0][0]
        symbol_merge = write_query.split("MERGE (s:Symbol", 1)[1]
        assert "start_line" in symbol_merge
        assert "end_line" in symbol_merge
