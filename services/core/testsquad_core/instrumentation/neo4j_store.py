import os
import json
from typing import List, Dict, Any, Optional
from .symbol_resolver import Symbol


class Neo4jStore:
    """Stores and retrieves test-symbol mappings in Neo4j using [:EVIDENCE] relationship."""
    
    def __init__(self, neo4j_client=None):
        self.neo4j_client = neo4j_client
    
    def store_mappings(self, mappings: List[Dict[str, Any]], project_id: int) -> int:
        """
        Store test-symbol mappings in Neo4j using batch UNWIND.
        
        Args:
            mappings: List of dicts with test_name, test_file, symbols
            project_id: Project ID for scoping
            
        Returns:
            Number of edges created
        """
        if not self.neo4j_client or not mappings:
            return 0
        
        edges = []
        for mapping in mappings:
            test_name = mapping.get("test_name", "")
            test_file = mapping.get("test_file", "")
            for symbol in mapping.get("symbols", []):
                if isinstance(symbol, tuple):
                    sym_name = symbol[0]
                    sym_type = symbol[1]
                    sym_start = symbol[2]
                    sym_end = symbol[3]
                    sym_file = symbol[4]
                else:
                    sym_name = symbol.name
                    sym_type = symbol.symbol_type
                    sym_start = symbol.start_line
                    sym_end = symbol.end_line
                    sym_file = symbol.file_path
                edges.append({
                    "test_name": test_name,
                    "test_file": test_file,
                    "symbol_name": sym_name,
                    "symbol_file": sym_file,
                    "symbol_type": sym_type,
                    "start_line": sym_start,
                    "end_line": sym_end,
                })
        
        return self._bulk_store_edges(edges, project_id)
    
    def _bulk_store_edges(self, edges: List[Dict], project_id: int) -> int:
        """Bulk create nodes and EVIDENCE edges using UNWIND."""
        if not edges:
            return 0
        
        query = """
        UNWIND $edges AS e
        MERGE (t:TestSymbol {
            name: e.test_name,
            file_path: e.test_file,
            project_id: $project_id
        })
        MERGE (s:Symbol {
            name: e.symbol_name,
            file_path: e.symbol_file,
            project_id: $project_id
        })
        SET s.symbol_type = e.symbol_type,
            s.start_line = e.start_line,
            s.end_line = e.end_line
        MERGE (t)-[:EVIDENCE {source: 'coverage', confidence: 1.0}]->(s)
        RETURN count(*) AS created
        """
        try:
            result = self.neo4j_client.query(query, {"edges": edges, "project_id": project_id})
            return result[0]["created"] if result else len(edges)
        except Exception as e:
            print(f"Warning: Failed to bulk store edges: {e}")
            return 0
    
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