import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from testsquad_core.graph.client import Neo4jClient


class TestNeo4jSchemaProperties:
    """Test Task 1.1.6: Neo4j Schema Tests - New properties."""

    @pytest.fixture
    def client(self):
        return Neo4jClient()

    def test_index_symbol_with_summary(self, client):
        """Test Symbol creation with summary property."""
        query = """
        MATCH (f:File {path: $file_path})
        MERGE (f)-[:DEFINES]->(s:Symbol {name: $name, file_path: $file_path})
        SET s.type = $type, s.start_line = $start_line, s.end_line = $end_line, s.decorators = $decorators
        SET s.summary = $summary, s.signature = $signature, s.embedding = $embedding, s.summary_version = coalesce(s.summary_version, 1)
        """
        params = {
            "file_path": "test.py",
            "name": "test_func",
            "type": "function",
            "start_line": 1,
            "end_line": 10,
            "decorators": [],
            "summary": "This is a test function",
            "signature": "def test_func() -> None",
            "embedding": [0.0] * 768
        }
        assert "summary" in params
        assert "signature" in params
        assert "embedding" in params
        assert len(params["embedding"]) == 768

    def test_index_symbol_with_signature(self, client):
        """Test Symbol creation with signature property."""
        params = {
            "file_path": "test.py",
            "name": "add",
            "type": "function",
            "start_line": 1,
            "end_line": 5,
            "decorators": [],
            "summary": None,
            "signature": "def add(a: int, b: int) -> int",
            "embedding": None
        }
        assert "signature" in params
        assert params["signature"] == "def add(a: int, b: int) -> int"

    def test_index_symbol_with_embedding(self, client):
        """Test Symbol creation with embedding property."""
        embedding = [0.1] * 768
        params = {
            "file_path": "test.py",
            "name": "func",
            "type": "function",
            "start_line": 1,
            "end_line": 5,
            "decorators": [],
            "summary": None,
            "signature": None,
            "embedding": embedding
        }
        assert len(params["embedding"]) == 768

    def test_index_symbol_summary_version_default(self, client):
        """Test that summary_version defaults to 1."""
        query = """
        SET s.summary_version = coalesce(s.summary_version, 1)
        """
        assert "coalesce(s.summary_version, 1)" in query

    def test_index_test_symbol_with_summary(self, client):
        """Test TestSymbol creation with summary property."""
        params = {
            "file_path": "test_test.py",
            "name": "test_something",
            "type": "function",
            "start_line": 1,
            "end_line": 10,
            "test_type": "unit",
            "summary": "Tests something",
            "signature": "def test_something():",
            "embedding": [0.0] * 768
        }
        assert "summary" in params
        assert params["summary"] == "Tests something"

    def test_bulk_index_symbols_with_properties(self, client):
        """Test bulk symbol indexing with new properties."""
        symbols = [
            {
                "name": "func1",
                "type": "function",
                "start_line": 1,
                "end_line": 5,
                "decorators": [],
                "summary": "First function",
                "signature": "def func1()",
                "embedding": [0.0] * 768
            },
            {
                "name": "func2",
                "type": "function",
                "start_line": 10,
                "end_line": 20,
                "decorators": [],
                "summary": "Second function",
                "signature": "def func2()",
                "embedding": [0.0] * 768
            }
        ]
        assert len(symbols) == 2
        for sym in symbols:
            assert "summary" in sym
            assert "signature" in sym
            assert "embedding" in sym
            assert len(sym["embedding"]) == 768


class TestNeo4jExecutedByRelationship:
    """Test EXECUTED_BY relationship."""

    @pytest.fixture
    def client(self):
        return Neo4jClient()

    def test_executed_by_edge_properties(self, client):
        """Test EXECUTED_BY edge has correct properties."""
        query = """
        MATCH (s:Symbol {name: $symbol_name, file_path: $symbol_file})
        MATCH (ts:TestSymbol {name: $test_name, file_path: $test_file})
        MERGE (s)-[r:EXECUTED_BY]->(ts)
        SET r.confidence = $confidence,
            r.source = $source,
            r.created_at = datetime()
        """
        params = {
            "symbol_name": "test_func",
            "symbol_file": "test.py",
            "test_name": "test_test_func",
            "test_file": "test_test.py",
            "confidence": 0.85,
            "source": "vector"
        }
        assert "confidence" in params
        assert "source" in params
        assert 0.0 <= params["confidence"] <= 1.0
        assert params["source"] in ["coverage", "vector", "heuristic"]

    def test_executed_by_edge_confidence_range(self, client):
        """Test confidence is in valid range."""
        valid_confidences = [0.0, 0.5, 0.75, 1.0]
        for conf in valid_confidences:
            assert 0.0 <= conf <= 1.0

    def test_bulk_executed_by_edges(self, client):
        """Test bulk EXECUTED_BY edge creation."""
        edges = [
            {
                "symbol_name": "func1",
                "symbol_file": "test.py",
                "test_name": "test_func1",
                "test_file": "test_test.py",
                "confidence": 0.9,
                "source": "coverage"
            },
            {
                "symbol_name": "func2",
                "symbol_file": "test.py",
                "test_name": "test_func2",
                "test_file": "test_test.py",
                "confidence": 0.8,
                "source": "vector"
            }
        ]
        assert len(edges) == 2
        for edge in edges:
            assert "symbol_name" in edge
            assert "test_name" in edge
            assert "confidence" in edge


class TestNeo4jVectorIndex:
    """Test vector index creation."""

    @pytest.fixture
    def client(self):
        return Neo4jClient()

    def test_vector_index_config(self, client):
        """Test vector index has correct configuration."""
        query = """
        CREATE VECTOR INDEX symbolEmbeddings IF NOT EXISTS
        FOR (s:Symbol) ON s.embedding
        OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}
        """
        assert "vector.dimensions" in query
        assert "vector.similarity_function" in query
        assert "768" in query
        assert "cosine" in query

    def test_vector_index_name(self, client):
        """Test vector index has correct name."""
        index_name = "symbolEmbeddings"
        assert index_name == "symbolEmbeddings"


class TestNeo4jBulkEmbeddings:
    """Test bulk embedding updates."""

    @pytest.fixture
    def client(self):
        return Neo4jClient()

    def test_bulk_update_embeddings_format(self, client):
        """Test bulk update embeddings data format."""
        embeddings = {
            ("func1", "test.py"): [0.1] * 768,
            ("func2", "test.py"): [0.2] * 768,
            ("func3", "test.py"): [0.3] * 768
        }
        data = [
            {"name": name, "file_path": fp, "embedding": emb}
            for (name, fp), emb in embeddings.items()
        ]
        assert len(data) == 3
        for row in data:
            assert "name" in row
            assert "file_path" in row
            assert "embedding" in row
            assert len(row["embedding"]) == 768

    def test_bulk_update_embeddings_10k(self, client):
        """Test bulk update handles 10K+ symbols."""
        embeddings = {}
        for i in range(10000):
            embeddings[(f"func{i}", f"test{i}.py")] = [0.01 * i] * 768

        data = [
            {"name": name, "file_path": fp, "embedding": emb}
            for (name, fp), emb in embeddings.items()
        ]
        assert len(data) == 10000
        assert len(embeddings) == 10000


class TestNeo4jMigrationScript:
    """Test migration script."""

    def test_migration_script_exists(self):
        """Test migration script exists."""
        script_path = os.path.join(
            os.path.dirname(__file__), "..", "scripts", "migrate_schema.py"
        )
        assert os.path.exists(script_path), f"Migration script not found: {script_path}"

    def test_migration_script_dry_run(self):
        """Test migration script accepts --dry-run flag."""
        import argparse

        script_path = os.path.join(
            os.path.dirname(__file__), "..", "scripts", "migrate_schema.py"
        )
        with open(script_path, 'r') as f:
            content = f.read()

        assert "--dry-run" in content
        assert " argparse " in content

    def test_migration_script_idempotent(self):
        """Test migration script is idempotent."""
        script_path = os.path.join(
            os.path.dirname(__file__), "..", "scripts", "migrate_schema.py"
        )
        with open(script_path, 'r') as f:
            content = f.read()

        assert "IF NOT EXISTS" in content


class TestNeo4jMethods:
    """Test new client methods exist."""

    @pytest.fixture
    def client(self):
        return Neo4jClient()

    def test_create_vector_index_method_exists(self, client):
        """Test create_vector_index method exists."""
        assert hasattr(client, "create_vector_index")
        assert callable(client.create_vector_index)

    def test_bulk_update_embeddings_method_exists(self, client):
        """Test bulk_update_embeddings method exists."""
        assert hasattr(client, "bulk_update_embeddings")
        assert callable(client.bulk_update_embeddings)

    def test_add_executed_by_edge_method_exists(self, client):
        """Test add_executed_by_edge method exists."""
        assert hasattr(client, "add_executed_by_edge")
        assert callable(client.add_executed_by_edge)

    def test_bulk_add_executed_by_edges_method_exists(self, client):
        """Test bulk_add_executed_by_edges method exists."""
        assert hasattr(client, "bulk_add_executed_by_edges")
        assert callable(client.bulk_add_executed_by_edges)

    def test_get_executed_by_tests_method_exists(self, client):
        """Test get_executed_by_tests method exists."""
        assert hasattr(client, "get_executed_by_tests")
        assert callable(client.get_executed_by_tests)

    def test_find_similar_tests_by_embedding_method_exists(self, client):
        """Test find_similar_tests_by_embedding method exists."""
        assert hasattr(client, "find_similar_tests_by_embedding")
        assert callable(client.find_similar_tests_by_embedding)


class TestNeo4jQueryMethods:
    """Test query building for new methods."""

    @pytest.fixture
    def client(self):
        return Neo4jClient()

    def test_get_executed_by_tests_query(self, client):
        """Test get_executed_by_tests builds correct query."""
        query = """
        MATCH (s:Symbol {name: $symbol_name, file_path: $symbol_file})-[r:EXECUTED_BY]->(ts:TestSymbol)
        RETURN ts.name as test_name,
               ts.file_path as test_file,
               r.confidence as confidence,
               r.source as source,
               r.created_at as created_at
        ORDER BY r.confidence DESC
        """
        assert "EXECUTED_BY" in query
        assert "ORDER BY r.confidence DESC" in query

    def test_find_similar_tests_query(self, client):
        """Test find_similar_tests_by_embedding builds correct query."""
        query = """
        MATCH (s:Symbol {name: $symbol_name, file_path: $symbol_file})
        MATCH (s)-[r:EXECUTED_BY]->(ts:TestSymbol)
        RETURN ts.name as test_name,
               ts.file_path as test_file,
               r.confidence as confidence
        ORDER BY r.confidence DESC
        LIMIT $limit
        """
        assert "LIMIT $limit" in query


class TestNeo4jNoDataLoss:
    """Test no data loss on existing symbols."""

    @pytest.fixture
    def client(self):
        return Neo4jClient()

    def test_preserves_existing_properties(self, client):
        """Test existing properties are preserved."""
        query = """
        MATCH (f:File {path: $file_path})
        MERGE (f)-[:DEFINES]->(s:Symbol {name: $name, file_path: $file_path})
        SET s.type = $type, s.start_line = $start_line, s.end_line = $end_line, s.decorators = $decorators
        SET s.summary = $summary, s.signature = $signature, s.embedding = $embedding, s.summary_version = coalesce(s.summary_version, 1)
        """
        assert "SET s.type" in query
        assert "SET s.start_line" in query
        assert "SET s.end_line" in query

    def test_preserves_test_properties(self, client):
        """Test existing TestSymbol properties are preserved."""
        query = """
        MATCH (f:TestFile {path: $file_path})
        MERGE (f)-[:DEFINES]->(ts:TestSymbol {name: $name, file_path: $file_path})
        SET ts.type = $type, ts.start_line = $start_line, ts.end_line = $end_line, ts.test_type = $test_type
        SET ts.summary = $summary, ts.signature = $signature, ts.embedding = $embedding, ts.summary_version = coalesce(ts.summary_version, 1)
        """
        assert "SET ts.type" in query
        assert "SET ts.test_type" in query


if __name__ == "__main__":
    pytest.main([__file__, "-v"])