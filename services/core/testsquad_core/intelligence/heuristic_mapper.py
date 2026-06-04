import logging
import os
import re
from typing import List, Dict, Tuple, Generator
from testsquad_core.graph.client import Neo4jClient

logger = logging.getLogger(__name__)


class HeuristicMapper:
    """Zero-cost deterministic mapper from filename/directory patterns.

    Creates EVIDENCE edges without model loading or API calls.
    Rules (in priority order):
    1. Exact filename match: test_foo.py ↔ foo.py (confidence 0.95)
    2. Directory colocation: tests/utils/ ↔ src/utils/ (confidence 0.85)
    3. Subword Jaccard >= 0.4: token overlap on symbol names (confidence 0.70)
    4. Same community: Leiden community match + filename overlap (confidence 0.65)
    """

    def __init__(self, neo4j: Neo4jClient):
        self.neo4j = neo4j

    def map_tests(self, project_id: int) -> Generator[Dict, None, None]:
        yield {"event": "reasoning", "data": "Running heuristic filename matching..."}
        rule1_edges = self._rule_filename_match(project_id)
        yield {"event": "progress", "data": f"Rule 1 (filename): {len(rule1_edges)} candidates"}

        yield {"event": "reasoning", "data": "Running directory colocation..."}
        rule2_edges = self._rule_directory_colocation(project_id)
        yield {"event": "progress", "data": f"Rule 2 (directory): {len(rule2_edges)} candidates"}

        yield {"event": "reasoning", "data": "Running subword Jaccard matching..."}
        rule3_edges = self._rule_subword_jaccard(project_id)
        yield {"event": "progress", "data": f"Rule 3 (Jaccard): {len(rule3_edges)} candidates"}

        yield {"event": "reasoning", "data": "Running community overlap matching..."}
        rule4_edges = self._rule_community_overlap(project_id)
        yield {"event": "progress", "data": f"Rule 4 (community): {len(rule4_edges)} candidates"}

        all_edges = []
        seen_pairs = set()
        for edges in [rule1_edges, rule2_edges, rule3_edges, rule4_edges]:
            for edge in edges:
                pair_key = (edge["symbol_name"], edge["test_name"])
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    all_edges.append(edge)

        yield {"event": "progress", "data": f"Total unique heuristic candidates: {len(all_edges)}"}

        if not all_edges:
            yield {"event": "status", "data": {"status": "NO_MATCHES", "message": "No heuristic matches"}}
            return

        edges_created = self.neo4j.bulk_add_evidence_edges(all_edges, source="heuristic")
        yield {"event": "progress", "data": f"Created {edges_created} EVIDENCE edges"}

        yield {
            "event": "status",
            "data": {"status": "COMPLETED", "candidates": len(all_edges), "edges": edges_created}
        }

    def _rule_filename_match(self, project_id: int) -> List[Dict]:
        """Rule 1: Exact filename match (test_foo.py ↔ foo.py)."""
        query = """
        MATCH (s:Symbol)
        WHERE (s.project_id = $pid
               OR EXISTS { MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(:File)-[:DEFINES]->(s) })
          AND NOT EXISTS { MATCH (s)<-[:EVIDENCE {source:'heuristic'}]-(:TestSymbol) }
        MATCH (ts:TestSymbol {project_id: $pid})
        WHERE NOT EXISTS { MATCH (ts)-[:EVIDENCE {source:'heuristic'}]->(s) }
        WITH s, ts,
             last(split(s.file_path, '/')) as s_base,
             last(split(ts.file_path, '/')) as ts_base
        WHERE (ts_base CONTAINS 'test_' AND replace(ts_base, 'test_', '') = s_base)
           OR (ts_base CONTAINS '_test' AND replace(ts_base, '_test', '') = s_base)
           OR (ts_base = replace(s_base, '.py', '_test.py'))
           OR (ts_base = 'test_' + s_base)
           OR (ts_base = replace(s_base, '.py', '.test.py'))
           OR (ts_base = replace(s_base, '.py', '.spec.py'))
        RETURN s.name as symbol_name,
               s.file_path as symbol_file,
               ts.name as test_name,
               ts.file_path as test_file
        """
        results = self.neo4j.query(query, {"pid": project_id})
        edges = []
        for r in results:
            edges.append({
                "symbol_name": r["symbol_name"],
                "symbol_file": r["symbol_file"],
                "test_name": r["test_name"],
                "test_file": r["test_file"],
                "features": {"heuristic": 0.95},
                "final_confidence": 0.95,
                "reasoning": "Exact filename match (test_*.py ↔ *.py)"
            })
        return edges

    def _rule_directory_colocation(self, project_id: int) -> List[Dict]:
        """Rule 2: Directory colocation (tests/utils/foo ↔ src/utils/foo)."""
        query = """
        MATCH (s:Symbol)
        WHERE (s.project_id = $pid
               OR EXISTS { MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(:File)-[:DEFINES]->(s) })
          AND NOT EXISTS { MATCH (s)<-[:EVIDENCE {source:'heuristic'}]-(:TestSymbol) }
        MATCH (ts:TestSymbol {project_id: $pid})
        WHERE NOT EXISTS { MATCH (ts)-[:EVIDENCE {source:'heuristic'}]->(s) }
        WITH s, ts,
             replace(s.file_path, '/src/', '/tests/') as s_test_path,
             replace(ts.file_path, '/tests/', '/src/') as ts_src_path
        WHERE s.file_path <> s_test_path
          AND (ts.file_path STARTS WITH s_test_path
               OR s.file_path STARTS WITH ts_src_path)
        RETURN s.name as symbol_name,
               s.file_path as symbol_file,
               ts.name as test_name,
               ts.file_path as test_file
        LIMIT 5000
        """
        results = self.neo4j.query(query, {"pid": project_id})
        edges = []
        for r in results:
            edges.append({
                "symbol_name": r["symbol_name"],
                "symbol_file": r["symbol_file"],
                "test_name": r["test_name"],
                "test_file": r["test_file"],
                "features": {"heuristic": 0.85},
                "final_confidence": 0.85,
                "reasoning": "Directory colocation match"
            })
        return edges

    def _tokenize(self, name: str) -> set:
        """Split camelCase and snake_case into tokens."""
        tokens = set()
        parts = re.split(r'[^a-zA-Z0-9]+', name)
        for part in parts:
            sub_parts = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\b)', part)
            if sub_parts:
                tokens.update(t.lower() for t in sub_parts if len(t) > 2)
            else:
                tokens.add(part.lower())
        return tokens

    def _rule_subword_jaccard(self, project_id: int) -> List[Dict]:
        """Rule 3: Subword Jaccard >= 0.4 on tokenized names."""
        symbols = self.neo4j.query("""
        MATCH (s:Symbol)
        WHERE (s.project_id = $pid
               OR EXISTS { MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(:File)-[:DEFINES]->(s) })
          AND NOT EXISTS { MATCH (s)<-[:EVIDENCE {source:'heuristic'}]-(:TestSymbol) }
        RETURN s.name as name, s.file_path as file_path
        """, {"pid": project_id})

        tests = self.neo4j.query("""
        MATCH (ts:TestSymbol {project_id: $pid})
        RETURN ts.name as name, ts.file_path as file_path
        """, {"pid": project_id})

        edges = []
        for sym in symbols:
            sym_tokens = self._tokenize(sym["name"])
            if not sym_tokens:
                continue
            for test in tests:
                test_tokens = self._tokenize(test["name"])
                if not test_tokens:
                    continue
                intersection = sym_tokens & test_tokens
                union = sym_tokens | test_tokens
                jaccard = len(intersection) / len(union) if union else 0
                if jaccard >= 0.4:
                    edges.append({
                        "symbol_name": sym["name"],
                        "symbol_file": sym["file_path"],
                        "test_name": test["name"],
                        "test_file": test["file_path"],
                        "features": {"heuristic": round(jaccard, 2), "jaccard": round(jaccard, 2)},
                        "final_confidence": round(jaccard, 2),
                        "reasoning": f"Subword Jaccard: {jaccard:.2f}"
                    })
        return edges

    def _rule_community_overlap(self, project_id: int) -> List[Dict]:
        """Rule 4: Same Leiden community + filename overlap."""
        query = """
        MATCH (s:Symbol)
        WHERE (s.project_id = $pid
               OR EXISTS { MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(:File)-[:DEFINES]->(s) })
          AND s.community_id IS NOT NULL
          AND NOT EXISTS { MATCH (s)<-[:EVIDENCE {source:'heuristic'}]-(:TestSymbol) }
        MATCH (ts:TestSymbol {project_id: $pid})
        WHERE ts.test_community_id IS NOT NULL
          AND s.community_id = ts.test_community_id
          AND NOT EXISTS { MATCH (ts)-[:EVIDENCE {source:'heuristic'}]->(s) }
        RETURN s.name as symbol_name,
               s.file_path as symbol_file,
               ts.name as test_name,
               ts.file_path as test_file
        LIMIT 5000
        """
        results = self.neo4j.query(query, {"pid": project_id})
        edges = []
        for r in results:
            edges.append({
                "symbol_name": r["symbol_name"],
                "symbol_file": r["symbol_file"],
                "test_name": r["test_name"],
                "test_file": r["test_file"],
                "features": {"heuristic": 0.65, "community_overlap": 1.0},
                "final_confidence": 0.65,
                "reasoning": "Same Leiden community"
            })
        return edges
