import logging
import os
from typing import List, Dict, Tuple, Optional, NamedTuple
from testsquad_core.graph.client import Neo4jClient
from testsquad_core.intelligence.embedder import Embedder

logger = logging.getLogger(__name__)


class VectorMapper:
    """Vector-based test mapping using multi-signal candidate generation.
    
    Candidate Generation Layers:
    - Layer 1: CALLS graph — direct edges from AST extraction
    - Layer 2: Filename heuristics — X.ts → X.test.ts, test_X.py → X.py
    - Layer 3: Community co-location — same Leiden community
    
    Pre-filter Logic:
    - Reduce N×N to N×k by directory/module
    """
    
    def __init__(self, neo4j: Neo4jClient, embedder: Optional[Embedder] = None):
        self.neo4j = neo4j
        self.embedder = embedder or Embedder()
    
    # --- Task 2.1.1: Core Methods ---
    
    def _get_unmapped_symbols(self, project_id: int) -> List[Dict]:
        """Get symbols without EVIDENCE or APPROVED_TEST edges.
        
        Returns:
            List of symbol dicts with name, file_path, type, community_id
        """
        query = """
        MATCH (s:Symbol)
        WHERE (s.project_id = $pid
               OR EXISTS { MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(:File)-[:DEFINES]->(s) })
          AND NOT (s)<-[:EVIDENCE]-(:TestSymbol)
          AND NOT (s)-[:APPROVED_TEST]->(:TestSymbol)
        RETURN s.name as name, 
               s.file_path as file_path, 
               s.type as type, 
               COALESCE(s.summary, "") as summary,
               COALESCE(s.community_id, 0) as community_id
        LIMIT 5000
        """
        return self.neo4j.query(query, {"pid": project_id})
    
    def _get_all_tests(self, project_id: int) -> List[Dict]:
        """Get all test symbols for a project."""
        query = """
        MATCH (ts:TestSymbol)
        WHERE ts.project_id = $pid
           OR EXISTS { MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(:TestFile)-[:DEFINES]->(ts) }
        RETURN ts.name as name,
               ts.file_path as file_path,
               ts.type as type,
               COALESCE(ts.summary, "") as summary,
               COALESCE(ts.test_community_id, 0) as test_community_id
        """
        return self.neo4j.query(query, {"pid": project_id})
    
    def _get_all_product_symbols(self, project_id: int) -> List[Dict]:
        """Get all product symbols for a project."""
        query = """
        MATCH (p:Project {sql_id: $pid})-[*1..2]->(s:Symbol)
        RETURN s.name as name,
               s.file_path as file_path,
               s.type as type,
               COALESCE(s.summary, "") as summary,
               COALESCE(s.community_id, 0) as community_id
        """
        return self.neo4j.query(query, {"pid": project_id})
    
    # --- Task 2.1.1: Layer 1 - CALLS Graph ---
    
    def _layer1_calls_graph(
        self,
        symbol: Dict,
        all_tests: List[Dict]
    ) -> List[Tuple[Dict, float]]:
        """Layer 1: Find tests via CALLS graph.
        
        Args:
            symbol: Product symbol
            all_tests: List of all test symbols
            
        Returns:
            List of (test, confidence) pairs
        """
        symbol_name = symbol.get("name", "")
        symbol_file = symbol.get("file_path", "")
        
        # Query CALLS relationship from Neo4j
        query = """
        MATCH (s:Symbol {name: $name, file_path: $file_path})-[r:CALLS]->(ts:TestSymbol)
        RETURN ts.name as name, ts.file_path as file_path, r.line as call_line
        """
        results = self.neo4j.query(query, {"name": symbol_name, "file_path": symbol_file})
        
        candidates = []
        test_map = {t["file_path"]: t for t in all_tests}
        
        for r in results:
            test_file = r.get("file_path")
            if test_file in test_map:
                candidates.append((test_map[test_file], 0.95))  # High confidence for direct calls
        
        return candidates
    
    # --- Task 2.1.1: Layer 2 - Filename Heuristics ---
    
    def _layer2_filename_heuristics(
        self,
        symbol: Dict,
        all_tests: List[Dict]
    ) -> List[Tuple[Dict, float]]:
        """Layer 2: Match via filename patterns.
        
        Patterns:
        - X.ts → X.test.ts
        - X.ts → X.spec.ts
        - test_X.py → X.py
        - X_test.py → X.py
        """
        symbol_file = symbol.get("file_path", "")
        symbol_name = symbol.get("name", "")
        
        if not symbol_file:
            return []
        
        # Build pattern mappings
        symbol_dir = os.path.dirname(symbol_file)
        symbol_base = os.path.splitext(os.path.basename(symbol_file))[0]
        symbol_ext = os.path.splitext(symbol_file)[1]
        
        candidates = []
        
        for test in all_tests:
            test_file = test.get("file_path", "")
            if not test_file:
                continue
            
            test_base = os.path.splitext(os.path.basename(test_file))[0]
            confidence = 0.0
            
            if symbol_ext in [".ts", ".tsx", ".js", ".jsx"]:
                # TypeScript/JavaScript patterns
                if test_base in [symbol_base + ".test", symbol_base + ".spec", "test." + symbol_base]:
                    confidence = 0.85
            elif symbol_ext == ".py":
                # Python patterns
                if test_base in [symbol_base + "_test", "test_" + symbol_base, symbol_base]:
                    confidence = 0.85
            
            if confidence > 0:
                # Same directory bonus
                test_dir = os.path.dirname(test_file)
                if test_dir == symbol_dir:
                    confidence += 0.1
                
                candidates.append((test, min(confidence, 0.95)))
        
        return candidates
    
    # --- Task 2.1.1: Layer 3 - Community Co-location ---
    
    def _layer3_community(
        self,
        symbol: Dict,
        all_tests: List[Dict]
    ) -> List[Tuple[Dict, float]]:
        """Layer 3: Filter by community co-location.
        
        Only considers tests in the same Leiden community.
        """
        community_id = symbol.get("community_id", 0)
        
        if community_id == 0:
            return []
        
        candidates = []
        
        for test in all_tests:
            test_community = test.get("test_community_id", 0)
            if test_community == community_id:
                candidates.append((test, 0.70))
        
        return candidates
    
    # --- Task 2.1.1: Pre-filter Logic ---
    
    def _build_candidate_tests(
        self,
        product_symbols: List[Dict],
        all_tests: List[Dict]
    ) -> List[Dict]:
        """Pre-filter to reduce N×N to N×k.
        
        Uses all 3 layers to generate candidates, then deduplicates
        and returns top-k per product symbol.
        
        Args:
            product_symbols: List of product symbols
            all_tests: List of all test symbols
            
        Returns:
            List of candidate pairs with confidence scores:
            {symbol_name, symbol_file, test_name, test_file, confidence, source}
        """
        # Build test lookup
        test_map = {}
        for t in all_tests:
            fp = t.get("file_path", "")
            if fp:
                test_map[fp] = t
        
        candidates = []
        max_candidates_per_symbol = 10
        
        for symbol in product_symbols:
            symbol_name = symbol.get("name", "")
            symbol_file = symbol.get("file_path", "")
            
            if not symbol_name or not symbol_file:
                continue
            
            # Collect from all layers
            layer_candidates = []
            
            # Layer 1: CALLS graph
            layer_candidates.extend(self._layer1_calls_graph(symbol, all_tests))
            
            # Layer 2: Filename heuristics
            layer_candidates.extend(self._layer2_filename_heuristics(symbol, all_tests))
            
            # Layer 3: Community
            layer_candidates.extend(self._layer3_community(symbol, all_tests))
            
            # Deduplicate by test file, keep highest confidence
            test_confidence = {}
            for test, conf in layer_candidates:
                test_file = test.get("file_path", "")
                if test_file and test_file not in test_confidence:
                    test_confidence[test_file] = conf
                elif test_file in test_confidence:
                    test_confidence[test_file] = max(test_confidence[test_file], conf)
            
            # Add top-k candidates
            sorted_tests = sorted(
                test_confidence.items(),
                key=lambda x: x[1],
                reverse=True
            )[:max_candidates_per_symbol]
            
            for test_file, confidence in sorted_tests:
                if test_file in test_map:
                    test = test_map[test_file]
                    candidates.append({
                        "symbol_name": symbol_name,
                        "symbol_file": symbol_file,
                        "test_name": test.get("name", ""),
                        "test_file": test_file,
                        "confidence": confidence,
                        "source": "layers"
                    })
        
        return candidates
    
    # --- Convenience Methods ---
    
    def generate_candidates(self, project_id: int) -> List[Dict]:
        """Generate candidate test mappings for all unmapped symbols.
        
        This is the main entry point for the candidate generation layer.
        
        Args:
            project_id: The SQL project ID
            
        Returns:
            List of candidate mappings with confidence scores
        """
        logger.info(f"Generating candidates for project {project_id}")
        
        # Get unmapped symbols
        unmapped = self._get_unmapped_symbols(project_id)
        logger.info(f"Found {len(unmapped)} unmapped symbols")
        
        if not unmapped:
            return []
        
        # Get all tests
        all_tests = self._get_all_tests(project_id)
        logger.info(f"Found {len(all_tests)} test symbols")
        
        if not all_tests:
            return []
        
        # Build candidates using pre-filter
        candidates = self._build_candidate_tests(unmapped, all_tests)
        logger.info(f"Generated {len(candidates)} candidate pairs")
        
        return candidates
    
    def get_statistics(self, project_id: int) -> Dict:
        """Get mapping statistics for a project."""
        unmapped = self._get_unmapped_symbols(project_id)
        all_tests = self._get_all_tests(project_id)
        
        return {
            "unmapped_symbols": len(unmapped),
            "total_tests": len(all_tests),
            "potential_comparisons": len(unmapped) * len(all_tests)
        }
    
    # --- Task 2.2.1: Vector Matching & Fusion ---
    
    class Match(NamedTuple):
        """A match between product symbol and test."""
        symbol_name: str
        symbol_file: str
        test_name: str
        test_file: str
        confidence: float
        source: str  # "vector", "bm25", "heuristic"
        reasoning: str
    
    def _match_vectors(
        self,
        candidates: List[Dict],
        threshold: float = 0.75
    ) -> List[Match]:
        """Match candidates using vector similarity and fusion.
        
        Args:
            candidates: List of candidate dicts from _build_candidate_tests
            threshold: Minimum confidence to create edge (default 0.75)
            
        Returns:
            List of Match objects above threshold
        """
        if not candidates:
            return []
        
        # Extract unique summaries for embedding
        product_summaries = []
        test_summaries = []
        unique_products = {}
        unique_tests = {}
        
        for c in candidates:
            sym_key = c["symbol_name"] + c["symbol_file"]
            test_key = c["test_name"] + c["test_file"]
            
            if sym_key not in unique_products:
                unique_products[sym_key] = c["symbol_file"]
                product_summaries.append(c.get("symbol_name", ""))
            
            if test_key not in unique_tests:
                unique_tests[test_key] = c["test_file"]
                test_summaries.append(c.get("test_name", ""))
        
        # Get embeddings
        product_embs = self.embedder.embed_batch(product_summaries) if product_summaries else []
        test_embs = self.embedder.embed_batch(test_summaries) if test_summaries else []
        
        # Compute similarity matrix
        matches = []
        
        for c in candidates:
            sym_key = c["symbol_name"] + c["symbol_file"]
            test_key = c["test_name"] + c["test_file"]
            
            if sym_key not in unique_products or test_key not in unique_tests:
                continue
            
            sym_idx = list(unique_products.keys()).index(sym_key)
            test_idx = list(unique_tests.keys()).index(test_key)
            
            # Vector similarity
            vector_score = 0.0
            if sym_idx < len(product_embs) and test_idx < len(test_embs):
                sim_results = self.embedder.similarity(
                    product_embs[sym_idx],
                    [test_embs[test_idx]],
                    top_k=1
                )
                vector_score = sim_results[0][1] if sim_results else 0.0
            
            # BM25 keyword overlap
            bm25_score = self._bm25_score(
                c.get("symbol_name", ""),
                c.get("test_name", "")
            )
            
            # Heuristic score from candidate
            heuristic_score = c.get("confidence", 0.0)
            
            # Fusion: max of all scores
            final_confidence = max(vector_score, bm25_score, heuristic_score)
            
            # Determine source
            if final_confidence == vector_score and vector_score > threshold:
                source = "vector"
                reasoning = f"Vector similarity: {vector_score:.2f}"
            elif final_confidence == bm25_score and bm25_score > threshold:
                source = "bm25"
                reasoning = f"Keyword overlap: {bm25_score:.2f}"
            elif final_confidence == heuristic_score and heuristic_score > threshold:
                source = "heuristic"
                reasoning = f"Name heuristic: {heuristic_score:.2f}"
            else:
                continue  # Below threshold
            
            matches.append(self.Match(
                symbol_name=c["symbol_name"],
                symbol_file=c["symbol_file"],
                test_name=c["test_name"],
                test_file=c["test_file"],
                confidence=final_confidence,
                source=source,
                reasoning=reasoning
            ))
        
        return matches
    
    def _bm25_score(self, text1: str, text2: str) -> float:
        """Compute simple keyword overlap score (BM25-lite).
        
        Args:
            text1: First text
            text2: Second text
            
        Returns:
            Score from 0.0 to 1.0
        """
        if not text1 or not text2:
            return 0.0
        
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1 & words2
        union = words1 | words2
        
        # Jaccard similarity
        score = len(intersection) / len(union) if union else 0.0
        
        return score
    
    def _create_edges(
        self,
        matches: List[Match],
        project_id: int
    ) -> int:
        """Create EVIDENCE edges in Neo4j.
        
        Args:
            matches: List of Match objects
            project_id: The SQL project ID
            
        Returns:
            Number of edges created
        """
        if not matches:
            return 0
        
        data = [
            {
                "symbol_name": m.symbol_name,
                "symbol_file": m.symbol_file,
                "test_name": m.test_name,
                "test_file": m.test_file,
                "confidence": m.confidence,
                "source": m.source,
                "reasoning": m.reasoning,
                "model": "vector_mapper"
            }
            for m in matches
        ]
        
        query = """
        UNWIND $data as row
        MATCH (p:Project {sql_id: $project_id})-[:CONTAINS]->(:File {path: row.symbol_file})-[:DEFINES]->(s:Symbol {name: row.symbol_name})
        MATCH (p)-[:CONTAINS]->(:TestFile {path: row.test_file})-[:DEFINES]->(ts:TestSymbol {name: row.test_name})
        MERGE (ts)-[r:EVIDENCE {source: 'vector'}]->(s)
        SET r.confidence = row.confidence,
            r.source = row.source,
            r.reasoning = row.reasoning,
            r.model = row.model,
            r.created_at = datetime()
        """
        
        result = self.neo4j.query(query, {"project_id": project_id, "data": data})
        
        return len(matches)
    
    def map_tests(
        self,
        project_id: int,
        threshold: float = 0.75
    ) -> Dict:
        """Full test mapping pipeline.
        
        Args:
            project_id: The SQL project ID
            threshold: Minimum confidence (default 0.75)
            
        Returns:
            Dict with mapping results and statistics
        """
        logger.info(f"Starting vector-based test mapping for project {project_id}")
        
        # Step 1: Generate candidates
        candidates = self.generate_candidates(project_id)
        logger.info(f"Generated {len(candidates)} candidates")
        
        # Step 2: Vector matching
        matches = self._match_vectors(candidates, threshold)
        logger.info(f"Matched {len(matches)} pairs above threshold {threshold}")
        
        # Step 3: Create edges
        edges_created = self._create_edges(matches, project_id)
        logger.info(f"Created {edges_created} EVIDENCE edges")
        
        return {
            "candidates": len(candidates),
            "matches": len(matches),
            "edges_created": edges_created
        }

    def apply_vector_matching(self, project_id: int, threshold: float = 0.6) -> int:
        """Apply vector matching and create edges. Returns number of edges created."""
        try:
            result = self.map_tests(project_id, threshold)
            return result.get("edges_created", 0)
        except Exception as e:
            logger.warning(f"Vector matching failed: {e}")
            return 0
        
        return {
            "candidates": len(candidates),
            "matches": len(matches),
            "edges_created": edges_created,
            "threshold": threshold
        }