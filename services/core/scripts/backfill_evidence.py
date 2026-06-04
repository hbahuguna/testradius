"""One-time backfill: convert [:TESTS] and [:SUGGESTED_TEST] to [:EVIDENCE] edges.

Phase 1: Write [:EVIDENCE] alongside old edges (safe, reversible).
Phase 2: Drop old edges after verification.

Usage:
    python scripts/backfill_evidence.py --project-id 1 --phase 1
    python scripts/backfill_evidence.py --project-id 1 --phase 2
"""
import argparse
from testsquad_core.graph.client import Neo4jClient


MAPPINGS = {
    "TESTS": ("coverage", 1.0),
    "SUGGESTED_TEST": ("llm", 0.7),
}


def phase_1(client: Neo4jClient, project_id: int):
    for old_rel, (source, default_conf) in MAPPINGS.items():
        # Handle TestSymbol→Symbol direction (TESTS edges)
        query1 = f"""
        MATCH (ts:TestSymbol)-[r:{old_rel}]->(s:Symbol)
        WHERE coalesce(ts.project_id, s.project_id, $project_id) = $project_id
        MERGE (ts)-[:EVIDENCE {{
            source: $source,
            confidence: COALESCE(r.confidence, $default_conf),
            migrated: true
        }}]->(s)
        """
        client.query(query1, {
            "project_id": project_id,
            "source": source,
            "default_conf": default_conf,
        })
        
        # Handle Symbol→TestSymbol direction (SUGGESTED_TEST edges)
        query2 = f"""
        MATCH (s:Symbol)-[r:{old_rel}]->(ts:TestSymbol)
        WHERE coalesce(s.project_id, ts.project_id, $project_id) = $project_id
        MERGE (ts)-[:EVIDENCE {{
            source: $source,
            confidence: COALESCE(r.confidence, $default_conf),
            migrated: true
        }}]->(s)
        """
        client.query(query2, {
            "project_id": project_id,
            "source": source,
            "default_conf": default_conf,
        })
        
        count = client.query(
            "MATCH (t)-[r:EVIDENCE {migrated: true}]->(s) RETURN count(r) AS c",
            {}
        )
        print(f"Migrated {old_rel} -> EVIDENCE. Total EVIDENCE edges: {count[0]['c']}")


def phase_2(client: Neo4jClient, project_id: int):
    for old_rel in ["TESTS", "SUGGESTED_TEST"]:
        # Drop edges in both directions
        query1 = f"""
        MATCH (ts:TestSymbol)-[r:{old_rel}]->(s:Symbol)
        WHERE coalesce(ts.project_id, s.project_id, $project_id) = $project_id
        DELETE r
        """
        client.query(query1, {"project_id": project_id})
        
        query2 = f"""
        MATCH (s:Symbol)-[r:{old_rel}]->(ts:TestSymbol)
        WHERE coalesce(s.project_id, ts.project_id, $project_id) = $project_id
        DELETE r
        """
        client.query(query2, {"project_id": project_id})
        
        print(f"Dropped {old_rel} edges for project {project_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--phase", type=int, choices=[1, 2], required=True)
    args = parser.parse_args()

    client = Neo4jClient()
    if args.phase == 1:
        phase_1(client, args.project_id)
    else:
        phase_2(client, args.project_id)
