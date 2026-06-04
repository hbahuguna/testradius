import json
import logging
import os
from typing import List, Dict, Optional
from testsquad_core.graph.client import Neo4jClient

logger = logging.getLogger(__name__)


class ActiveLearner:
    """Improve cross-encoder by feeding LLM-verified pairs back as training data.

    When LLM says YES but cross-encoder says < 0.5 -> add as positive
    When LLM says NO but cross-encoder says > 0.7 -> add as hard negative
    """

    def __init__(self, neo4j: Neo4jClient):
        self.neo4j = neo4j

    def collect_corrections(
        self,
        candidates: List[Dict],
        llm_threshold: float = 0.8,
        ce_low_threshold: float = 0.5,
        ce_high_threshold: float = 0.7
    ) -> Dict[str, List[Dict]]:
        """Collect pairs where LLM and cross-encoder disagree.

        llm_verification is 0.0-1.0 (LLM confidence normalized).
        cross_encoder_score is 0.0-1.0 (sigmoid output).

        Returns:
            {"add_positives": [...], "add_hard_negatives": [...]}
        """
        add_positives = []
        add_hard_negatives = []

        for c in candidates:
            llm_score = c.get("llm_verification", 0.0)
            ce_score = c.get("cross_encoder_score", 0.0)

            if llm_score >= llm_threshold and ce_score < ce_low_threshold:
                add_positives.append({
                    "symbol_name": c["symbol_name"],
                    "symbol_file": c.get("symbol_file", ""),
                    "symbol_code": c.get("symbol_code", c.get("symbol_name", "")),
                    "test_name": c["test_name"],
                    "test_file": c.get("test_file", ""),
                    "test_code": c.get("test_code", c.get("test_name", "")),
                    "label": 1.0
                })

            if llm_score == 0.0 and ce_score > ce_high_threshold:
                add_hard_negatives.append({
                    "symbol_name": c["symbol_name"],
                    "symbol_file": c.get("symbol_file", ""),
                    "symbol_code": c.get("symbol_code", c.get("symbol_name", "")),
                    "test_name": c["test_name"],
                    "test_file": c.get("test_file", ""),
                    "test_code": c.get("test_code", c.get("test_name", "")),
                    "label": 0.0
                })

        logger.info(
            f"Active learning: {len(add_positives)} new positives, "
            f"{len(add_hard_negatives)} new hard negatives"
        )
        return {
            "add_positives": add_positives,
            "add_hard_negatives": add_hard_negatives
        }

    def export_corrections(
        self,
        corrections: Dict[str, List[Dict]],
        output_path: str = "training_data/corrections.jsonl"
    ) -> int:
        """Export corrections as JSONL for cross-encoder retraining."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        count = 0
        with open(output_path, "w") as f:
            for pair in corrections.get("add_positives", []):
                f.write(json.dumps(pair) + "\n")
                count += 1
            for pair in corrections.get("add_hard_negatives", []):
                f.write(json.dumps(pair) + "\n")
                count += 1
        logger.info(f"Exported {count} corrections to {output_path}")
        return count
