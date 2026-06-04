#!/usr/bin/env python3
"""Apply cross-encoder scoring + ensemble fusion to existing EVIDENCE edges.

Usage:
    source venv/bin/activate
    python scripts/apply_ensemble.py --project-id 888
"""
import json
import logging
import os
import sys
from typing import List, Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "core"))
from testsquad_core.graph.client import Neo4jClient
from testsquad_core.intelligence.code_reader import CodeReader
from testsquad_core.intelligence.cross_encoder import CrossEncoderScorer
from testsquad_core.intelligence.ensemble_fuser import EnsembleFuser
from testsquad_core.intelligence.training_data import TrainingDataExporter

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def step1_score_heuristic_edges(client: Neo4jClient, project_id: int):
    """Score existing heuristic edges with cross-encoder to add feature."""
    # Fetch heuristic edges with symbol/test summaries
    edges = client.query("""
    MATCH (ts:TestSymbol)-[r:EVIDENCE {source: 'heuristic'}]->(s:Symbol)
    WHERE s.project_id = $pid OR EXISTS {
        MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(:File)-[:DEFINES]->(s)
    }
    RETURN elementId(r) as edge_id,
           s.name as symbol_name,
           s.file_path as symbol_file,
           coalesce(s.summary, s.name) as symbol_code,
           s.start_line as symbol_start_line,
           s.end_line as symbol_end_line,
           ts.name as test_name,
           ts.file_path as test_file,
           coalesce(ts.summary, ts.name) as test_code,
           r.features as features
    """, {"pid": project_id})

    if not edges:
        logger.info("No heuristic edges to score")
        return

    logger.info(f"Scoring {len(edges)} heuristic edges with cross-encoder...")
    reader = CodeReader(base_dirs=["/tmp/testbed-py-key-value-20260512_135821"])
    scorer = CrossEncoderScorer(
        model_path="models/cross_encoder/cross_encoder_model/"
    )

    candidates = []
    for e in edges:
        features = json.loads(e["features"]) if isinstance(e["features"], str) else (e["features"] or {})
        symbol_code = reader.read_symbol(
            e["symbol_file"], e["symbol_start_line"], e["symbol_end_line"]
        ) if e.get("symbol_start_line") else e["symbol_code"]
        test_code = reader.read_test(e["test_file"], e["test_name"])
        candidates.append({
            "edge_id": e["edge_id"],
            "symbol_name": e["symbol_name"],
            "symbol_file": e["symbol_file"],
            "symbol_code": symbol_code,
            "test_name": e["test_name"],
            "test_file": e["test_file"],
            "test_code": test_code or e["test_code"],
            "features": features,
        })

    scored = scorer.score_pairs(candidates)
    logger.info(f"Cross-encoder scores computed")

    # Update features with cross-encoder score
    updated = 0
    for c in scored:
        ce_score = c.get("cross_encoder_score", 0.0)
        c["features"]["cross_encoder"] = round(ce_score, 4)
        features_json = json.dumps(c["features"])
        client.query("""
        MATCH (ts:TestSymbol)-[r:EVIDENCE]->(s:Symbol)
        WHERE elementId(r) = $edge_id
        SET r.features = $features
        """, {"edge_id": c["edge_id"], "features": features_json})
        updated += 1

    logger.info(f"Updated {updated} edges with cross_encoder feature")


def step2_train_fuser(client: Neo4jClient, project_id: int):
    """Train EnsembleFuser and propagate final_confidence."""
    # Fetch positive samples: heuristic edges with features and high confidence
    pos_raw = client.query("""
    MATCH (ts:TestSymbol)-[r:EVIDENCE {source: 'heuristic'}]->(s:Symbol)
    WHERE (s.project_id = $pid OR EXISTS {
        MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(:File)-[:DEFINES]->(s)
    })
      AND r.features IS NOT NULL
      AND r.final_confidence >= 0.5
    RETURN r.features as features
    LIMIT 5000
    """, {"pid": project_id})

    pos = []
    for row in pos_raw:
        f = json.loads(row["features"]) if isinstance(row["features"], str) else (row["features"] or {})
        pos.append({"features": f})

    exporter = TrainingDataExporter(client)
    _, neg_raw = exporter.export_all(
        project_id, pos_limit=0, neg_limit=5000, hard_neg_limit=0
    )
    neg_raw = neg_raw or []

    # For negative samples, use heuristic features that would be low
    neg = []
    for n in neg_raw:
        neg.append({
            "features": {
                "heuristic": 0.0,
                "siamese": 0.0,
                "cross_encoder": 0.0,
                "jaccard": 0.0,
                "call_graph": 0.0,
                "community_overlap": 0.0,
                "mpnet": 0.0,
                "llm_verification": 0.0,
            }
        })

    if not pos:
        logger.info("No positive samples for fuser training")
        return

    logger.info(f"Training EnsembleFuser on {len(pos)} positive, {len(neg)} negative samples")
    fuser = EnsembleFuser()
    fuser.train(pos, neg)
    logger.info(f"Learned weights: {fuser.weights}")

    # Propagate final_confidence to ALL edges with features
    to_update = client.query("""
    MATCH (ts:TestSymbol)-[r:EVIDENCE]->(s:Symbol)
    WHERE (s.project_id = $pid OR EXISTS {
        MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(:File)-[:DEFINES]->(s)
    })
      AND r.features IS NOT NULL
    RETURN elementId(r) as edge_id, r.features as features
    LIMIT 20000
    """, {"pid": project_id})

    updated = 0
    for row in to_update:
        f = json.loads(row["features"]) if isinstance(row["features"], str) else (row["features"] or {})
        score = fuser.predict(f)
        client.query("""
        MATCH (ts:TestSymbol)-[r:EVIDENCE]->(s:Symbol)
        WHERE elementId(r) = $edge_id
        SET r.final_confidence = $score
        """, {"edge_id": row["edge_id"], "score": round(score, 4)})
        updated += 1

    logger.info(f"Propagated final_confidence to {updated} edges")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", type=int, default=888)
    parser.add_argument("--skip-cross-encoder", action="store_true")
    parser.add_argument("--skip-fuser", action="store_true")
    args = parser.parse_args()

    client = Neo4jClient()

    if not args.skip_cross_encoder:
        logger.info("=== Step 1: Cross-encoder scoring ===")
        step1_score_heuristic_edges(client, args.project_id)

    if not args.skip_fuser:
        logger.info("\n=== Step 2: Ensemble fusion ===")
        step2_train_fuser(client, args.project_id)

    client.close()
    logger.info("\nDone")


if __name__ == "__main__":
    main()
