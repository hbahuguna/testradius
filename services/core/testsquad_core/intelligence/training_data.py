import logging
import random
from typing import List, Dict, Optional, Tuple
from testsquad_core.graph.client import Neo4jClient

logger = logging.getLogger(__name__)


class TrainingDataExporter:
    """Export training pairs from Neo4j for cross-encoder fine-tuning."""

    def __init__(
        self,
        neo4j: Neo4jClient,
        code_reader: Optional["CodeReader"] = None,
        base_dirs: Optional[List[str]] = None,
    ):
        self.neo4j = neo4j
        self._code_reader = code_reader
        self._code_reader_imported = code_reader is not None
        if code_reader is not None and base_dirs:
            code_reader._base_dirs = base_dirs

    @staticmethod
    def _detect_base_dirs(items: List[Dict]) -> List[str]:
        """Extract project base directory from absolute symbol paths.
        
        For path /tmp/testbed-xxx/src/key_value/..., returns /tmp/testbed-xxx/
        """
        dirs = set()
        for item in items:
            fp = item.get("file_path") or item.get("symbol_file", "")
            if fp and fp.startswith("/"):
                parts = fp.split("/")
                if len(parts) >= 3:
                    base = "/".join(parts[:3])
                    dirs.add(base)
        return sorted(dirs)

    def _enrich_with_code(self, pairs: List[Dict]) -> List[Dict]:
        """Replace LLM summary with actual source code from disk."""
        if not self._code_reader_imported or self._code_reader is None:
            return pairs
        for p in pairs:
            sym_file = p.get("symbol_file", "")
            sym_start = p.get("symbol_start_line")
            sym_end = p.get("symbol_end_line")
            if sym_start and sym_end:
                p["symbol_code"] = self._code_reader.read_symbol(
                    sym_file, sym_start, sym_end
                )
            test_file = p.get("test_file", "")
            test_name = p.get("test_name", "")
            test_code = self._code_reader.read_test(test_file, test_name)
            if test_code:
                p["test_code"] = test_code
        return pairs

    def export_positive_pairs(
        self,
        project_id: int,
        min_confidence: float = 0.8,
        limit: int = 25000
    ) -> List[Dict]:
        """Export positive pairs from existing EVIDENCE edges."""
        query = """
        MATCH (s:Symbol)
        WHERE s.project_id = $pid
           OR EXISTS { MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(:File)-[:DEFINES]->(s) }
        MATCH (ts:TestSymbol)-[r:EVIDENCE]->(s)
        WHERE r.confidence >= $min_confidence
           OR r.final_confidence >= $min_confidence
        RETURN s.name as symbol_name,
               s.file_path as symbol_file,
               coalesce(s.summary, s.name) as symbol_code,
               s.start_line as symbol_start_line,
               s.end_line as symbol_end_line,
               ts.name as test_name,
               ts.file_path as test_file,
               coalesce(ts.summary, ts.name) as test_code,
               coalesce(r.confidence, r.final_confidence, 0.5) as confidence,
               r.source as source
        ORDER BY confidence DESC
        LIMIT $limit
        """
        pairs = self.neo4j.query(query, {
            "pid": project_id,
            "min_confidence": min_confidence,
            "limit": limit
        })
        return self._enrich_with_code(pairs)

    def export_negative_pairs(
        self,
        project_id: int,
        limit: int = 10000
    ) -> List[Dict]:
        """Export negative pairs by sampling in Python.

        Instead of a cross-product query (too slow), fetch all symbols
        and tests, then randomly pair symbols with tests from different
        file trees that have no EVIDENCE connection.
        """
        symbols = self.neo4j.query("""
        MATCH (s:Symbol)
        WHERE s.project_id = $pid
           OR EXISTS { MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(:File)-[:DEFINES]->(s) }
        RETURN s.name as name,
               s.file_path as file_path,
               s.start_line as symbol_start_line,
               s.end_line as symbol_end_line,
               coalesce(s.summary, s.name) as code
        """, {"pid": project_id})

        tests = self.neo4j.query("""
        MATCH (ts:TestSymbol {project_id: $pid})
        RETURN ts.name as name,
               ts.file_path as file_path,
               coalesce(ts.summary, ts.name) as code
        """, {"pid": project_id})

        existing = self.neo4j.query("""
        MATCH (ts:TestSymbol)-[r:EVIDENCE]->(s:Symbol)
        WHERE s.project_id = $pid
        RETURN s.name as symbol_name, ts.name as test_name
        """, {"pid": project_id})
        existing_set = {(e["symbol_name"], e["test_name"]) for e in existing}

        def _discriminator(fp: str) -> str:
            if not fp:
                return ""
            parts = fp.split("/")
            for p in parts:
                if p and p != "tmp" and not p.startswith("testbed-") and not p.startswith("20"):
                    return p
            return parts[-1] if parts else ""

        pairs = []
        random.seed(42)

        while len(pairs) < limit and len(pairs) < len(symbols) * len(tests):
            sym = random.choice(symbols)
            t = random.choice(tests)
            key = (sym["name"], t["name"])
            if key in existing_set:
                continue
            sym_disc = _discriminator(sym["file_path"])
            test_disc = _discriminator(t["file_path"])
            if sym_disc == test_disc or sym_disc == "" or test_disc == "":
                continue
            pairs.append({
                "symbol_name": sym["name"],
                "symbol_file": sym["file_path"],
                "symbol_start_line": sym.get("symbol_start_line"),
                "symbol_end_line": sym.get("symbol_end_line"),
                "symbol_code": sym["code"],
                "test_name": t["name"],
                "test_file": t["file_path"],
                "test_code": t["code"],
            })

        logger.info(f"Exported {len(pairs)} negative pairs (sampled from {len(symbols)} symbols x {len(tests)} tests)")
        return self._enrich_with_code(pairs)

    def export_hard_negatives(
        self,
        project_id: int,
        limit: int = 5000
    ) -> List[Dict]:
        """Export hard negatives: same-directory pairs with no EVIDENCE.

        Also done in Python to avoid slow cross-product Cypher queries.
        """
        symbols = self.neo4j.query("""
        MATCH (s:Symbol)
        WHERE s.project_id = $pid
           OR EXISTS { MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(:File)-[:DEFINES]->(s) }
        RETURN s.name as name,
               s.file_path as file_path,
               s.start_line as symbol_start_line,
               s.end_line as symbol_end_line,
               coalesce(s.summary, s.name) as code
        """, {"pid": project_id})

        tests = self.neo4j.query("""
        MATCH (ts:TestSymbol {project_id: $pid})
        RETURN ts.name as name,
               ts.file_path as file_path,
               coalesce(ts.summary, ts.name) as code
        """, {"pid": project_id})

        existing = self.neo4j.query("""
        MATCH (ts:TestSymbol)-[r:EVIDENCE]->(s:Symbol)
        WHERE s.project_id = $pid
        RETURN s.name as symbol_name, ts.name as test_name
        """, {"pid": project_id})
        existing_set = {(e["symbol_name"], e["test_name"]) for e in existing}

        def _discriminator(fp: str) -> str:
            if not fp:
                return ""
            parts = fp.split("/")
            for p in parts:
                if p and p != "tmp" and not p.startswith("testbed-") and not p.startswith("20"):
                    return p
            return parts[-1] if parts else ""

        def file_dir(fp: str) -> str:
            return "/".join(fp.split("/")[:-1])

        pairs = []
        random.seed(42)

        for _ in range(limit * 10):
            if len(pairs) >= limit:
                break
            sym = random.choice(symbols)
            t = random.choice(tests)
            key = (sym["name"], t["name"])
            if key in existing_set:
                continue
            sym_disc = _discriminator(sym["file_path"])
            test_disc = _discriminator(t["file_path"])
            if sym_disc != test_disc or sym_disc == "":
                continue
            if file_dir(sym["file_path"]) == file_dir(t["file_path"]):
                pairs.append({
                    "symbol_name": sym["name"],
                    "symbol_file": sym["file_path"],
                    "symbol_start_line": sym.get("symbol_start_line"),
                    "symbol_end_line": sym.get("symbol_end_line"),
                    "symbol_code": sym["code"],
                    "test_name": t["name"],
                    "test_file": t["file_path"],
                    "test_code": t["code"],
                })

        logger.info(f"Exported {len(pairs)} hard negative pairs")
        return self._enrich_with_code(pairs)

    def export_all(
        self,
        project_id: int,
        pos_limit: int = 25000,
        neg_limit: int = 10000,
        hard_neg_limit: int = 5000
    ) -> Tuple[List[Dict], List[Dict]]:
        """Export all pairs. Returns (positive_pairs, negative_pairs)."""
        positive = self.export_positive_pairs(project_id, limit=pos_limit)
        negative_random = self.export_negative_pairs(project_id, limit=neg_limit)
        negative_hard = self.export_hard_negatives(project_id, limit=hard_neg_limit)
        all_negative = negative_random + negative_hard
        logger.info(
            f"Exported {len(positive)} positive, {len(all_negative)} negative "
            f"({len(negative_random)} random + {len(negative_hard)} hard)"
        )
        return positive, all_negative
