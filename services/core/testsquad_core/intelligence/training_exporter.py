import logging
import random
from typing import List, Dict
from datetime import datetime
from testsquad_core.graph.client import Neo4jClient

logger = logging.getLogger(__name__)


class TrainingExporter:
    """Export training data for Siamese network fine-tuning.
    
    Uses plain Python lists instead of pandas for Docker compatibility.
    """
    
    def __init__(self, neo4j: Neo4jClient):
        self.neo4j = neo4j
    
    def export_candidate_pairs(
        self,
        project_id: int,
        min_confidence: float = 0.6,
        limit: int = 5000
    ) -> List[Dict]:
        """Export labeled candidate pairs for training.
        
        Args:
            project_id: The SQL project ID
            min_confidence: Minimum confidence threshold
            limit: Maximum pairs to export
            
        Returns:
            List of dicts with keys: sym_id, sym_path, sym_summary, test_id, test_path, test_summary, confidence, source, reasoning, label
        """
        evidence_query = """
        MATCH (p:Project {sql_id: $pid})-[*1..2]->(s:Symbol)<-[r:EVIDENCE]-(ts:TestSymbol)
        WHERE r.confidence >= $min_conf
        RETURN s.name as symbol_name,
               s.file_path as symbol_file,
               COALESCE(s.summary, s.name) as symbol_summary,
               ts.name as test_name,
               ts.file_path as test_file,
               COALESCE(ts.summary, ts.name) as test_summary,
               r.confidence as confidence,
               r.source as source,
               r.reasoning as reasoning,
               0 as label
        LIMIT $limit
        """
        
        approved_query = """
        MATCH (p:Project {sql_id: $pid})-[*1..2]->(s:Symbol)-[r:APPROVED_TEST]->(ts:TestSymbol)
        RETURN s.name as symbol_name,
               s.file_path as symbol_file,
               COALESCE(s.summary, s.name) as symbol_summary,
               ts.name as test_name,
               ts.file_path as test_file,
               COALESCE(ts.summary, ts.name) as test_summary,
               1.0 as confidence,
               'manual_approval' as source,
               'Approved by human' as reasoning,
               1 as label
        LIMIT $limit
        """
        
        evidence = self.neo4j.query(evidence_query, {
            "pid": project_id,
            "min_conf": min_confidence,
            "limit": limit
        })
        
        approved = self.neo4j.query(approved_query, {
            "pid": project_id,
            "limit": limit
        })
        
        all_pairs = (evidence or []) + (approved or [])
        
        if not all_pairs:
            logger.warning(f"No training pairs found for project {project_id}")
            return []
        
        # Rename columns for training
        for pair in all_pairs:
            pair["sym_id"] = pair.pop("symbol_name")
            pair["sym_path"] = pair.pop("symbol_file")
            pair["sym_summary"] = pair.pop("symbol_summary")
            pair["test_id"] = pair.pop("test_name")
            pair["test_path"] = pair.pop("test_file")
            pair["test_summary"] = pair.pop("test_summary")
        
        # Filter by limit
        if len(all_pairs) > limit:
            all_pairs = all_pairs[:limit]
        
        logger.info(f"Exported {len(all_pairs)} training pairs (EVIDENCE: {len(evidence or [])}, APPROVED: {len(approved or [])})")
        
        return all_pairs
    
    def export_hard_negatives(
        self,
        project_id: int,
        max_negatives: int = 1000
    ) -> List[Dict]:
        """Generate hard negative samples for training."""
        unmapped_query = """
        MATCH (p:Project {sql_id: $pid})-[*1..2]->(s:Symbol)
        WHERE NOT (s)<-[:EVIDENCE]-(:TestSymbol)
        AND NOT (s)-[:APPROVED_TEST]->(:TestSymbol)
        RETURN s.name as name, s.file_path as file_path, COALESCE(s.summary, s.name) as summary
        LIMIT $max
        """
        
        unmapped = self.neo4j.query(unmapped_query, {
            "pid": project_id,
            "max": max_negatives
        })
        
        if not unmapped:
            return []
        
        test_query = """
        MATCH (p:Project {sql_id: $pid})-[*1..2]->(ts:TestSymbol)
        RETURN ts.name as name, ts.file_path as file_path, COALESCE(ts.summary, ts.name) as summary
        LIMIT $max
        """
        
        tests = self.neo4j.query(test_query, {
            "pid": project_id,
            "max": max_negatives
        })
        
        if not tests:
            return []
        
        random.seed(42)
        
        negatives = []
        count = min(len(unmapped), len(tests), max_negatives)
        for i in range(count):
            sym = unmapped[i % len(unmapped)]
            test = tests[i % len(tests)]
            negatives.append({
                "sym_id": sym["name"],
                "sym_path": sym["file_path"],
                "sym_summary": sym["summary"],
                "test_id": test["name"],
                "test_path": test["file_path"],
                "test_summary": test["summary"],
                "confidence": 0.0,
                "source": "hard_negative",
                "reasoning": "Random unmapped pair",
                "label": 0
            })
        
        logger.info(f"Generated {len(negatives)} hard negative samples")
        
        return negatives
    
    def get_training_statistics(self, project_id: int) -> Dict:
        """Get training data statistics for a project."""
        evidence = self.neo4j.query("""
            MATCH (p:Project {sql_id: $pid})-[*1..2]->(s:Symbol)<-[r:EVIDENCE]-(:TestSymbol)
            RETURN count(r) as count
        """, {"pid": project_id})
        
        approved = self.neo4j.query("""
            MATCH (p:Project {sql_id: $pid})-[*1..2]->(s:Symbol)-[:APPROVED_TEST]->(:TestSymbol)
            RETURN count(*) as count
        """, {"pid": project_id})
        
        unmapped = self.neo4j.query("""
            MATCH (p:Project {sql_id: $pid})-[*1..2]->(s:Symbol)
            WHERE NOT (s)<-[:EVIDENCE]-(:TestSymbol)
            AND NOT (s)-[:APPROVED_TEST]->(:TestSymbol)
            RETURN count(s) as count
        """, {"pid": project_id})
        
        return {
            "evidence_edges": evidence[0].get("count", 0) if evidence else 0,
            "approved_test_edges": approved[0].get("count", 0) if approved else 0,
            "unmapped_symbols": unmapped[0].get("count", 0) if unmapped else 0
        }