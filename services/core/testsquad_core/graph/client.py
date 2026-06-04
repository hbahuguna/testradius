import os
import logging
from typing import List, Dict, Any, Optional
from neo4j import GraphDatabase

logger = logging.getLogger("testsquad")

class Neo4jClient:
    def __init__(self, uri: str = None, user: str = None, password: str = None):
        self.uri = uri or os.getenv("NEO4J_URL", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "testsquad_password")
        self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))

    def close(self):
        self.driver.close()

    def query(self, cypher: str, parameters: dict = None):
        with self.driver.session() as session:
            result = session.run(cypher, parameters)
            return [record.data() for record in result]

    def ensure_constraints(self):
        """Initialize graph constraints and indexes."""
        queries = [
            "CREATE CONSTRAINT project_id IF NOT EXISTS FOR (p:Project) REQUIRE p.sql_id IS UNIQUE",
            "CREATE CONSTRAINT file_path IF NOT EXISTS FOR (f:File) REQUIRE f.path IS UNIQUE",
            "CREATE INDEX symbol_name IF NOT EXISTS FOR (s:Symbol) ON (s.name)"
        ]
        for q in queries:
            try:
                self.query(q)
            except Exception as e:
                # Some versions of Neo4j/drivers might handle constraint creation differently
                logger.warning("Could not create constraint: %s", e)

    def sync_project(self, project_id: int, name: str):
        """Ensure a SQL Project has a matching Neo4j node."""
        query = """
        MERGE (p:Project {sql_id: $project_id})
        SET p.name = $name
        RETURN p
        """
        return self.query(query, {"project_id": project_id, "name": name})

    def index_file(self, project_id: int, path: str, language: str):
        """Index a file and link it to its project."""
        query = """
        MERGE (f:File {path: $path})
        SET f.language = $language
        WITH f
        MATCH (p:Project {sql_id: $project_id})
        MERGE (p)-[:CONTAINS]->(f)
        RETURN f
        """
        return self.query(query, {"project_id": project_id, "path": path, "language": language})

    def index_symbol(self, file_path: str, name: str, sym_type: str, start_line: int, end_line: int, decorators: list = None, summary: str = None, signature: str = None, embedding: list = None):
        """Creates or updates a Symbol node and links it to its File."""
        query = """
        MATCH (f:File {path: $file_path})
        MERGE (f)-[:DEFINES]->(s:Symbol {name: $name, file_path: $file_path})
        SET s.type = $type, s.start_line = $start_line, s.end_line = $end_line, s.decorators = $decorators
        SET s.summary = $summary, s.signature = $signature, s.embedding = $embedding, s.summary_version = coalesce(s.summary_version, 1)
        """
        return self.query(query, {
            "file_path": file_path, "name": name, "type": sym_type, 
            "start_line": start_line, "end_line": end_line,
            "decorators": decorators or [],
            "summary": summary,
            "signature": signature,
            "embedding": embedding
        })

    def index_file_symbols(self, project_id: int, file_path: str, symbols: List[Dict], language: str):
        """Bulk creates or updates symbols for a file using UNWIND."""
        query = """
        MATCH (p:Project {sql_id: $project_id})
        MERGE (p)-[:CONTAINS]->(f:File {path: $file_path})
        SET f.language = $language
        WITH f
        UNWIND $symbols as sym
        MERGE (f)-[:DEFINES]->(s:Symbol {name: sym.name, file_path: $file_path})
        SET s.type = sym.type, s.start_line = sym.start_line, s.end_line = sym.end_line, s.decorators = sym.decorators
        SET s.summary = sym.summary, s.signature = sym.signature, s.embedding = sym.embedding, s.summary_version = coalesce(s.summary_version, 1)
        """
        return self.query(query, {
            "project_id": project_id,
            "file_path": file_path,
            "language": language,
            "symbols": symbols
        })

    def index_test_file(self, project_id: int, file_path: str, language: str):
        """Creates or updates an Automation TestFile node and links it to the Project."""
        query = """
        MATCH (p:Project {sql_id: $project_id})
        MERGE (p)-[:CONTAINS]->(f:TestFile {path: $file_path})
        SET f.language = $language
        """
        return self.query(query, {"project_id": project_id, "file_path": file_path, "language": language})

    def index_test_file_symbols(self, project_id: int, file_path: str, symbols: List[Dict], language: str, test_type: str = "unit"):
        """Bulk creates or updates test symbols for a file using UNWIND."""
        query = """
        MATCH (p:Project {sql_id: $project_id})
        MERGE (p)-[:CONTAINS]->(f:TestFile {path: $file_path})
        SET f.language = $language
        WITH f
        UNWIND $symbols as sym
        MERGE (f)-[:DEFINES]->(ts:TestSymbol {name: sym.name, file_path: $file_path})
        SET ts.type = sym.type, ts.start_line = sym.start_line, ts.end_line = sym.end_line, ts.test_type = $test_type
        SET ts.summary = sym.summary, ts.signature = sym.signature, ts.embedding = sym.embedding, ts.summary_version = coalesce(ts.summary_version, 1)
        """
        return self.query(query, {
            "project_id": project_id,
            "file_path": file_path,
            "language": language,
            "symbols": symbols,
            "test_type": test_type
        })

    def add_test_import(self, project_id: int, from_path: str, to_path: str):
        """Creates an IMPORTS relationship between two test files within a project."""
        query = """
        MATCH (p:Project {sql_id: toInteger($pid)})
        MATCH (p)-[:CONTAINS]->(f1:TestFile {path: $from_path})
        MATCH (p)-[:CONTAINS]->(f2:TestFile {path: $to_path})
        MERGE (f1)-[:IMPORTS]->(f2)
        """
        return self.query(query, {"pid": project_id, "from_path": from_path, "to_path": to_path})

    def add_test_call(self, project_id: int, from_file: str, from_symbol: str, to_file: str, to_line: int):
        """Adds a CALLS relationship between test symbols."""
        query = """
        MATCH (p:Project {sql_id: toInteger($pid)})
        MATCH (p)-[:CONTAINS]->(:TestFile {path: $from_file})-[:DEFINES]->(ts1:TestSymbol {name: $from_name})
        MATCH (p)-[:CONTAINS]->(:TestFile {path: $to_file})-[:DEFINES]->(ts2:Symbol)
        WHERE ts2.start_line <= $to_line AND ts2.end_line >= $to_line
        MERGE (ts1)-[r:CALLS_PRODUCT]->(ts2)
        SET r.resolved_at_line = $to_line
        RETURN r
        """
        return self.query(query, {
            "pid": project_id,
            "from_name": from_symbol,
            "from_file": from_file,
            "to_file": to_file,
            "to_line": to_line
        })

    def index_test_symbol(self, file_path: str, name: str, sym_type: str, start_line: int, end_line: int, test_type: str = "frontend", summary: str = None, signature: str = None, embedding: list = None):
        """Creates or updates a TestSymbol node and links it to its TestFile."""
        query = """
        MATCH (f:TestFile {path: $file_path})
        MERGE (f)-[:DEFINES]->(ts:TestSymbol {name: $name, file_path: $file_path})
        SET ts.type = $type, ts.start_line = $start_line, ts.end_line = $end_line, ts.test_type = $test_type
        SET ts.summary = $summary, ts.signature = $signature, ts.embedding = $embedding, ts.summary_version = coalesce(ts.summary_version, 1)
        """
        return self.query(query, {
            "file_path": file_path, "name": name, "type": sym_type, 
            "start_line": start_line, "end_line": end_line,
            "test_type": test_type,
            "summary": summary,
            "signature": signature,
            "embedding": embedding
        })

    def add_relationship(self, project_id: int, from_node: dict, to_node: dict, rel_type: str):
        """Generic method to add a relationship between nodes (e.g., CALLS, IMPORTS)."""
        # from_node and to_node should contain enough metadata to identify them uniquely
        
        if rel_type == "IMPORTS":
            query = """
            MATCH (p:Project {sql_id: toInteger($pid)})
            MATCH (p)-[:CONTAINS]->(f1:File {path: $from_path})
            MATCH (p)-[:CONTAINS]->(f2:File {path: $to_path})
            MERGE (f1)-[:IMPORTS]->(f2)
            """
            return self.query(query, {"pid": project_id, "from_path": from_node["path"], "to_path": to_node["path"]})
        
        elif rel_type == "CALLS":
            query = """
            MATCH (p:Project {sql_id: toInteger($pid)})
            MATCH (p)-[:CONTAINS]->(:File)-[:DEFINES]->(s1:Symbol {name: $from_name, file_path: $from_file})
            MATCH (p)-[:CONTAINS]->(:File)-[:DEFINES]->(s2:Symbol {name: $to_name, file_path: $to_file})
            MERGE (s1)-[:CALLS]->(s2)
            """
            return self.query(query, {
                "pid": project_id,
                "from_name": from_node["name"], "from_file": from_node["file_path"],
                "to_name": to_node["name"], "to_file": to_node["file_path"]
            })

    def add_precise_call(self, project_id: int, from_file: str, from_symbol: str, to_file: str, to_line: int):
        """
        Adds a CALLS relationship by resolving the target line to a specific Symbol node.
        """
        query = """
        MATCH (p:Project {sql_id: toInteger($pid)})
        MATCH (p)-[:CONTAINS]->(:File)-[:DEFINES]->(s1:Symbol {name: $from_name, file_path: $from_file})
        MATCH (p)-[:CONTAINS]->(:File {path: $to_file})-[:DEFINES]->(s2:Symbol)
        WHERE s2.start_line <= $to_line AND s2.end_line >= $to_line
        MERGE (s1)-[r:CALLS]->(s2)
        SET r.precision = "high", r.resolved_at_line = $to_line
        RETURN r
        """
        return self.query(query, {
            "pid": project_id,
            "from_name": from_symbol,
            "from_file": from_file,
            "to_file": to_file,
            "to_line": to_line
        })

    def add_file_import(self, project_id: int, from_path: str, to_path: str):
        """Creates an IMPORTS relationship between two files within a project."""
        query = """
        MATCH (p:Project {sql_id: toInteger($pid)})
        MATCH (p)-[:CONTAINS]->(f1:File {path: $from_path})
        MATCH (p)-[:CONTAINS]->(f2:File {path: $to_path})
        MERGE (f1)-[:IMPORTS]->(f2)
        """
        return self.query(query, {"pid": project_id, "from_path": from_path, "to_path": to_path})

    def update_symbol_summary(self, file_path: str, name: str, summary: str, priority: int = 5):
        """Update semantic summary and priority score for a symbol."""
        query = """
        MATCH (s:Symbol {name: $name, file_path: $file_path})
        SET s.summary = $summary, s.priority_risk_index = $priority
        RETURN s
        """
        return self.query(query, {
            "file_path": file_path, 
            "name": name, 
            "summary": summary,
            "priority": priority
        })

    def tag_symbol_as_entry_point(self, file_path: str, name: str, surface_type: str):
        """Tag a symbol as a public entry point."""
        query = """
        MATCH (s:Symbol {name: $name, file_path: $file_path})
        SET s.is_entry_point = true, s.surface_type = $surface_type
        RETURN s
        """
        return self.query(query, {"file_path": file_path, "name": name, "surface_type": surface_type})

    def update_file_git_metrics(self, file_path: str, commit_count: int, author_count: int):
        """Update git metrics for all symbols within a specific file."""
        query = """
        MATCH (f:File {path: $file_path})-[:DEFINES]->(s:Symbol)
        SET s.commit_count = $commit_count, s.author_count = $author_count
        RETURN count(s) as updated_count
        """
        return self.query(query, {
            "file_path": file_path, 
            "commit_count": commit_count, 
            "author_count": author_count
        })

    def update_symbol_coverage(self, file_path: str, name: str, is_covered: bool, coverage_score: float):
        """Update coverage status and score for a symbol."""
        query = """
        MATCH (s:Symbol {name: $name, file_path: $file_path})
        SET s.is_covered = $is_covered, s.coverage_score = $coverage_score
        RETURN s
        """
        return self.query(query, {
            "file_path": file_path, 
            "name": name, 
            "is_covered": is_covered, 
            "coverage_score": coverage_score
        })

    def bulk_update_risk_scores(self, scored_data: List[Dict]):
        """Bulk update risk scores using node IDs."""
        query = """
        UNWIND $data as row
        MATCH (s:Symbol) WHERE elementId(s) = row.node_id
        SET s.priority_risk_index = row.pri
        RETURN count(s) as updated_count
        """
        return self.query(query, {"data": scored_data})

    def bulk_update_communities(self, community_data: List[Dict]):
        """
        Bulk update community IDs for symbols.
        `community_data` should be a list of dicts: [{"name": "func_name", "file_path": "path/to/file", "community_id": 1}, ...]
        """
        query = """
        UNWIND $data as row
        MATCH (s:Symbol {name: row.name, file_path: row.file_path})
        SET s.community_id = row.community_id
        RETURN count(s) as updated_count
        """
        return self.query(query, {"data": community_data})

    def bulk_update_test_communities(self, community_data: List[Dict]):
        """
        Bulk update test community IDs for TestSymbols.
        `community_data` should be a list of dicts: [{"name": "test_name", "file_path": "path/to/test", "test_community_id": 1}, ...]
        """
        query = """
        UNWIND $data as row
        MATCH (ts:TestSymbol {name: row.name, file_path: row.file_path})
        SET ts.test_community_id = row.test_community_id
        RETURN count(ts) as updated_count
        """
        return self.query(query, {"data": community_data})

    def get_communities(self, project_id: int):
        """Fetch symbols grouped by community ID for a given project."""
        query = """
        MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(f:File)-[:DEFINES]->(s:Symbol)
        WHERE s.community_id IS NOT NULL
        RETURN s.community_id as id, 
               collect({name: s.name, type: s.type, file_path: s.file_path, priority: s.priority_risk_index}) as symbols
        ORDER BY size(symbols) DESC
        """
        return self.query(query, {"pid": project_id})

    def get_community_graph(self, project_id: int, limit: int = 500, offset: int = 0):
        """Fetch nodes and edges for visualizing the codebase communities with pagination."""
        query = """
        MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(:File)-[:DEFINES]->(s:Symbol)
        WHERE s.community_id IS NOT NULL
        WITH s
        ORDER BY s.priority_risk_index DESC
        SKIP $offset
        LIMIT $limit
        
        WITH collect(s) as nodes
        UNWIND nodes as s
        // Link discovery within the selected set (Structural + Behavioral)
        OPTIONAL MATCH (s)-[r:CALLS|IMPORTS|INHERITS]->(t:Symbol)
        WHERE t IN nodes
        RETURN 
            [n in nodes | {
                id: elementId(n), 
                name: n.name, 
                type: n.type, 
                community_id: n.community_id, 
                val: n.priority_risk_index
            }] as nodes,
            collect(DISTINCT {
                source: elementId(s), 
                target: elementId(t), 
                type: type(r)
            }) as links
        """
        result = self.query(query, {"pid": project_id, "limit": limit, "offset": offset})
        if result and len(result) > 0:
            row = result[0]
            # Filter out null links from the OPTIONAL MATCH
            links = [l for l in row.get("links", []) if l.get("source") and l.get("target")]
            return {"nodes": row.get("nodes", []), "links": links}
        return {"nodes": [], "links": []}

    def index_document(self, project_id: int, file_path: str, content: str):
        """Creates or updates a Document node and links it to its Project."""
        query = """
        MATCH (p:Project {sql_id: $project_id})
        MERGE (p)-[:CONTAINS]->(d:Document {path: $file_path})
        SET d.content = $content
        RETURN d
        """
        return self.query(query, {"project_id": project_id, "file_path": file_path, "content": content})

    def add_document_mention(self, doc_path: str, symbol_name: str, symbol_file: str):
        """Creates a MENTIONS relationship from a Document to a Symbol."""
        query = """
        MATCH (d:Document {path: $doc_path})
        MATCH (s:Symbol {name: $symbol_name, file_path: $symbol_file})
        MERGE (d)-[:MENTIONS]->(s)
        """
        return self.query(query, {"doc_path": doc_path, "symbol_name": symbol_name, "symbol_file": symbol_file})

    def get_all_symbols(self, project_id: int):
        """Fetch all symbols for a given project for mention linking."""
        query = """
        MATCH (p:Project {sql_id: $pid})-[*1..2]->(s:Symbol)
        RETURN s.name as name, s.file_path as file_path
        """
        return self.query(query, {"pid": project_id})

    # --- Task 1.1.5: Vector Embedding Schema ---

    def create_vector_index(self) -> None:
        """Create vector index for Symbol embeddings (768-dim cosine)."""
        query = """
        CREATE VECTOR INDEX symbolEmbeddings IF NOT EXISTS
        FOR (s:Symbol) ON s.embedding
        OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}
        """
        try:
            self.query(query)
        except Exception as e:
            logger.warning("Could not create vector index: %s", e)

    def bulk_update_embeddings(self, project_id: int, embeddings: Dict[str, List[float]]) -> int:
        """Bulk update embeddings for symbols.
        
        Args:
            project_id: The SQL project ID
            embeddings: Dict mapping (name, file_path) -> embedding vector
            
        Returns:
            Number of symbols updated
        """
        data = [
            {"name": name, "file_path": fp, "embedding": emb}
            for (name, fp), emb in embeddings.items()
        ]
        
        if not data:
            return 0
            
        query = """
        UNWIND $data as row
        MATCH (p:Project {sql_id: $project_id})-[:CONTAINS]->(:File)-[:DEFINES]->(s:Symbol {name: row.name, file_path: row.file_path})
        SET s.embedding = row.embedding, s.summary_version = 1
        RETURN count(s) as updated_count
        """
        result = self.query(query, {"project_id": project_id, "data": data})
        return result[0].get("updated_count", 0) if result else 0

    def add_executed_by_edge(
        self,
        symbol_name: str,
        symbol_file: str,
        test_name: str,
        test_file: str,
        confidence: float,
        source: str = "coverage"
    ) -> None:
        """Create EXECUTED_BY relationship from Symbol to TestSymbol.
        
        Args:
            symbol_name: Name of the product symbol
            symbol_file: File path of the product symbol
            test_name: Name of the test symbol
            test_file: File path of the test symbol
            confidence: Confidence score (0.0 to 1.0)
            source: Source of the mapping (coverage|vector|heuristic)
        """
        query = """
        MATCH (s:Symbol {name: $symbol_name, file_path: $symbol_file})
        MATCH (ts:TestSymbol {name: $test_name, file_path: $test_file})
        MERGE (s)-[r:EXECUTED_BY]->(ts)
        SET r.confidence = $confidence,
            r.source = $source,
            r.created_at = datetime()
        """
        self.query(query, {
            "symbol_name": symbol_name,
            "symbol_file": symbol_file,
            "test_name": test_name,
            "test_file": test_file,
            "confidence": confidence,
            "source": source
        })

    def bulk_add_executed_by_edges(self, edges: List[Dict]) -> int:
        """Bulk create EXECUTED_BY relationships.
        
        Args:
            edges: List of dicts with keys:
                - symbol_name, symbol_file, test_name, test_file, confidence, source
                
        Returns:
            Number of edges created
        """
        if not edges:
            return 0
            
        data = [
            {
                "symbol_name": e["symbol_name"],
                "symbol_file": e["symbol_file"],
                "test_name": e["test_name"],
                "test_file": e["test_file"],
                "confidence": e.get("confidence", 0.75),
                "source": e.get("source", "coverage")
            }
            for e in edges
        ]
        
        query = """
        UNWIND $edges as edge
        MATCH (s:Symbol {name: edge.symbol_name, file_path: edge.symbol_file})
        MATCH (ts:TestSymbol {name: edge.test_name, file_path: edge.test_file})
        MERGE (s)-[r:EXECUTED_BY]->(ts)
        SET r.confidence = edge.confidence,
            r.source = edge.source,
            r.created_at = datetime()
        RETURN count(r) as edge_count
        """
        result = self.query(query, {"edges": data})
        return result[0].get("edge_count", 0) if result else 0

    def get_executed_by_tests(self, symbol_name: str, symbol_file: str) -> List[Dict]:
        """Get all tests that execute a given symbol via EXECUTED_BY edges."""
        query = """
        MATCH (s:Symbol {name: $symbol_name, file_path: $symbol_file})-[r:EXECUTED_BY]->(ts:TestSymbol)
        RETURN ts.name as test_name,
               ts.file_path as test_file,
               r.confidence as confidence,
               r.source as source,
               r.created_at as created_at
        ORDER BY r.confidence DESC
        """
        return self.query(query, {"symbol_name": symbol_name, "symbol_file": symbol_file})

    def find_similar_tests_by_embedding(
        self,
        symbol_name: str,
        symbol_file: str,
        limit: int = 10
    ) -> List[Dict]:
        """Find similar tests using vector similarity (requires vector index)."""
        query = """
        MATCH (s:Symbol {name: $symbol_name, file_path: $symbol_file})
        MATCH (s)-[r:EXECUTED_BY]->(ts:TestSymbol)
        RETURN ts.name as test_name,
               ts.file_path as test_file,
               r.confidence as confidence
        ORDER BY r.confidence DESC
        LIMIT $limit
        """
        return self.query(query, {"symbol_name": symbol_name, "symbol_file": symbol_file, "limit": limit})

    def bulk_add_siamese_edges(
        self,
        edges: List[Dict],
        model: str = "siamese"
    ) -> int:
        """Bulk create EVIDENCE relationship edges with Siamese model properties.

        Args:
            edges: List of dicts with keys:
                - symbol_name, symbol_file, test_name, test_file
                - confidence, siamese_confidence, mpnet_confidence, heuristic_confidence
                - final_confidence, reasoning
            model: Model type used ("siamese", "mpnet", "ensemble")

        Returns:
            Number of edges created
        """
        if not edges:
            return 0

        data = [
            {
                "symbol_name": e["symbol_name"],
                "symbol_file": e["symbol_file"],
                "test_name": e["test_name"],
                "test_file": e["test_file"],
                "confidence": e.get("confidence", 0.75),
                "siamese_confidence": e.get("siamese_confidence", 0.0),
                "mpnet_confidence": e.get("mpnet_confidence", 0.0),
                "heuristic_confidence": e.get("heuristic_confidence", 0.0),
                "final_confidence": e.get("final_confidence", e.get("confidence", 0.75)),
                "reasoning": e.get("reasoning", ""),
                "model": model,
            }
            for e in edges
        ]

        query = """
        UNWIND $edges as edge
        MATCH (s:Symbol {name: edge.symbol_name, file_path: edge.symbol_file})
        MATCH (ts:TestSymbol {name: edge.test_name, file_path: edge.test_file})
        MERGE (ts)-[r:EVIDENCE {source: 'siamese'}]->(s)
        SET r.confidence = edge.confidence,
            r.siamese_confidence = edge.siamese_confidence,
            r.mpnet_confidence = edge.mpnet_confidence,
            r.heuristic_confidence = edge.heuristic_confidence,
            r.final_confidence = edge.final_confidence,
            r.reasoning = edge.reasoning,
            r.model = edge.model,
            r.created_at = datetime()
        RETURN count(r) as edge_count
        """
        result = self.query(query, {"edges": data})
        return result[0].get("edge_count", 0) if result else 0

    def bulk_add_evidence_edges(self, edges: List[Dict], source: str = "heuristic") -> int:
        """Bulk create EVIDENCE edges with feature vector.

        Args:
            edges: List of dicts with keys:
                - symbol_name, symbol_file
                - test_name, test_file
                - features: dict of {feature_name: score}
                - final_confidence: float or None (set by ensemble stage)
                - reasoning: str
            source: Source label (heuristic, siamese, cross_encoder, ensemble)

        Returns:
            Number of edges created
        """
        if not edges:
            return 0

        import json
        data = [
            {
                "symbol_name": e["symbol_name"],
                "symbol_file": e["symbol_file"],
                "test_name": e["test_name"],
                "test_file": e["test_file"],
                "features_json": json.dumps(e.get("features", {})),
                "final_confidence": e.get("final_confidence"),
                "reasoning": e.get("reasoning", ""),
                "source": source
            }
            for e in edges
        ]

        query = """
        UNWIND $edges as edge
        MATCH (s:Symbol {name: edge.symbol_name, file_path: edge.symbol_file})
        MATCH (ts:TestSymbol {name: edge.test_name, file_path: edge.test_file})
        MERGE (ts)-[r:EVIDENCE {source: edge.source}]->(s)
        SET r.features = edge.features_json,
            r.final_confidence = edge.final_confidence,
            r.reasoning = edge.reasoning,
            r.created_at = datetime()
        RETURN count(r) as edge_count
        """
        result = self.query(query, {"edges": data})
        return result[0].get("edge_count", 0) if result else 0

    def get_evidence_features(self, project_id: int, source: str = None) -> List[Dict]:
        """Get all EVIDENCE edges with features for ensemble training.

        Args:
            project_id: The SQL project ID
            source: Filter by source (coverage, heuristic, siamese, etc.)

        Returns:
            List of dicts with symbol, test, features, final_confidence
            features is parsed from JSON string back to dict.
        """
        import json
        source_filter = "AND r.source = $source" if source else ""
        params = {"pid": project_id}
        if source:
            params["source"] = source

        query = f"""
        MATCH (s:Symbol)
        WHERE s.project_id = $pid
           OR EXISTS {{ MATCH (p:Project {{sql_id: $pid}})-[:CONTAINS]->(:File)-[:DEFINES]->(s) }}
        MATCH (ts:TestSymbol)-[r:EVIDENCE]->(s)
        {source_filter}
        RETURN s.name as symbol_name,
               s.file_path as symbol_file,
               ts.name as test_name,
               ts.file_path as test_file,
               r.features as features,
               r.final_confidence as final_confidence,
               r.source as source
        """
        results = self.query(query, params)
        for r in results:
            if isinstance(r.get("features"), str):
                try:
                    r["features"] = json.loads(r["features"])
                except (json.JSONDecodeError, TypeError):
                    r["features"] = {}
        return results

    def get_mappings_by_model(
        self,
        project_id: int,
        model: str
    ) -> List[Dict]:
        """Get test mappings filtered by model type."""
        query = """
        MATCH (p:Project {sql_id: $project_id})-[:CONTAINS]->(:File)-[:DEFINES]->(s:Symbol)
        MATCH (ts:TestSymbol)-[r:EVIDENCE]->(s)
        WHERE r.model = $model
        RETURN s.name as symbol_name,
               s.file_path as symbol_file,
               ts.name as test_name,
               ts.file_path as test_file,
               r.siamese_confidence as siamese_confidence,
               r.mpnet_confidence as mpnet_confidence,
               r.final_confidence as confidence,
               r.model as model,
               r.reasoning as reasoning
        ORDER BY r.final_confidence DESC
        """
        return self.query(query, {"project_id": project_id, "model": model})

    def compare_model_mappings(
        self,
        project_id: int
    ) -> Dict:
        """Compare mapping counts across different models."""
        query = """
        MATCH (p:Project {sql_id: $project_id})-[:CONTAINS]->(:File)-[:DEFINES]->(s:Symbol)
        MATCH (ts:TestSymbol)-[r:EVIDENCE]->(s)
        RETURN r.model as model, count(*) as count
        """
        results = self.query(query, {"project_id": project_id})
        
        counts = {"siamese": 0, "mpnet": 0, "ensemble": 0, "vector_mapper": 0}
        for r in results:
            model = r.get("model", "unknown")
            count = r.get("count", 0)
            if model in counts:
                counts[model] = count
        
        return counts
