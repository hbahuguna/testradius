import os
from typing import List, Dict, Any, Optional
from .symbol_resolver import Symbol


class Neo4jStore:
    """Stores and retrieves test-symbol mappings in Neo4j using [:EVIDENCE] relationship."""
    
    def __init__(self, neo4j_client=None):
        self.neo4j_client = neo4j_client
    
    def store_mappings(self, mappings: List[Dict[str, Any]], project_id: int) -> int:
        """
        Store test-symbol mappings in Neo4j.
        
        Args:
            mappings: List of dicts with test_name, test_file, symbols
            project_id: Project ID for scoping
            
        Returns:
            Number of edges created
        """
        if not self.neo4j_client or not mappings:
            return 0
        
        edges_created = 0
        
        for mapping in mappings:
            test_name = mapping.get("test_name", "")
            test_file = mapping.get("test_file", "")
            symbols = mapping.get("symbols", [])
            
            for symbol in symbols:
                self._store_test_symbol_edge(
                    project_id=project_id,
                    test_name=test_name,
                    test_file=test_file,
                    symbol=symbol
                )
                edges_created += 1
        
        return edges_created
    
    def _store_test_symbol_edge(
        self,
        project_id: int,
        test_name: str,
        test_file: str,
        symbol: Symbol
    ) -> None:
        """Store a single test-symbol edge in Neo4j using [:EVIDENCE] relationship."""
        if not self.neo4j_client:
            return
        
        query = """
        MERGE (t:TestSymbol {
            name: $test_name,
            file_path: $test_file,
            project_id: $project_id
        })
        MERGE (s:Symbol {
            name: $symbol_name,
            file_path: $symbol_file,
            project_id: $project_id
        })
        SET s.symbol_type = $symbol_type,
            s.start_line = $symbol_start,
            s.end_line = $symbol_end
        MERGE (t)-[:EVIDENCE {source: 'coverage', confidence: 1.0}]->(s)
        """
        
        try:
            params = {
                "test_name": test_name,
                "test_file": test_file,
                "project_id": project_id,
                "symbol_name": symbol.name,
                "symbol_type": symbol.symbol_type,
                "symbol_file": symbol.file_path,
                "symbol_start": symbol.start_line,
                "symbol_end": symbol.end_line
            }
            self.neo4j_client.query(query, params)
        except Exception as e:
            print(f"Warning: Failed to store edge: {e}")
    
    def get_impacted_tests(
        self,
        project_id: int,
        changed_symbols: List[str]
    ) -> List[Dict[str, Any]]:
        """Get tests that cover the given symbols using [:EVIDENCE] relationship."""
        if not self.neo4j_client:
            return []
        
        query = """
        MATCH (t:TestSymbol)-[e:EVIDENCE]->(s:Symbol)
        WHERE s.project_id = $project_id
          AND s.name IN $changed_symbols
        RETURN t.name as test_name, t.file_path as test_file,
               e.confidence as confidence, e.source as source
        ORDER BY test_name
        """
        
        try:
            params = {
                "project_id": project_id,
                "changed_symbols": changed_symbols
            }
            results = self.neo4j_client.query(query, params)
            return [
                {
                    "test_name": r["test_name"],
                    "test_file": r["test_file"],
                    "confidence": r["confidence"]
                }
                for r in results
            ]
        except Exception as e:
            print(f"Warning: Failed to query impacted tests: {e}")
            return []