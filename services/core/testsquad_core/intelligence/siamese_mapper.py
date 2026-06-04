import logging
from typing import List, Dict, Optional, Tuple, Generator, NamedTuple
from testsquad_core.graph.client import Neo4jClient
from testsquad_core.intelligence.siamese_config import SiameseConfig
from testsquad_core.intelligence.multi_embedder import MultiModelEmbedder

logger = logging.getLogger(__name__)


class Match(NamedTuple):
    """Represents a test mapping match."""
    symbol_name: str
    symbol_file: str
    symbol_summary: str
    test_name: str
    test_file: str
    test_summary: str
    confidence: float
    siamese_confidence: float = 0.0
    mpnet_confidence: float = 0.0
    heuristic_confidence: float = 0.0
    source: str = "siamese"
    reasoning: str = ""


class SiameseMapper:
    """Primary mapping engine using fine-tuned Siamese network.
    
    Combines:
    - VectorMapper candidate generation (layers 1-3)
    - MultiModelEmbedder for embeddings
    - Max fusion for confidence scoring
    
    Pipeline:
    1. Get unmapped symbols from Neo4j
    2. Generate candidates using CALLS graph, filename, community
    3. Generate embeddings with Siamese model
    4. Compute similarity and fusion scores
    5. Create EVIDENCE edges with detailed properties
    """
    
    DEFAULT_THRESHOLD_SIAMESE = 0.75
    DEFAULT_THRESHOLD_MPNET = 0.85
    
    def __init__(
        self,
        neo4j: Neo4jClient,
        config: Optional[SiameseConfig] = None,
        embedder: Optional[MultiModelEmbedder] = None
    ):
        self.neo4j = neo4j
        self.config = config or SiameseConfig()
        self.embedder = embedder or MultiModelEmbedder(
            siamese_path=self.config.model_path,
            target_dim=self.config.embedding_dim,
            siamese_batch_size=self.config.siamese_batch_size,
            mpnet_batch_size=self.config.mpnet_batch_size,
        )
    
    # --- Candidate Generation (reusing VectorMapper layers) ---
    
    def _get_unmapped_symbols(self, project_id: int) -> List[Dict]:
        """Get symbols without existing EVIDENCE or APPROVED_TEST edges."""
        query = """
        MATCH (s:Symbol)
        WHERE (s.project_id = $pid
               OR EXISTS { MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(:File)-[:DEFINES]->(s) })
          AND NOT (s)<-[:EVIDENCE]-(:TestSymbol)
          AND NOT (s)-[:APPROVED_TEST]->(:TestSymbol)
        RETURN s.name as name, 
               s.file_path as file_path, 
               COALESCE(s.summary, "") as summary,
               COALESCE(s.community_id, 0) as community_id
        LIMIT 5000
        """
        return self.neo4j.query(query, {"pid": project_id})
    
    def _get_all_symbols(self, project_id: int) -> List[Dict]:
        """Get ALL symbols for a project (no filter)."""
        query = """
        MATCH (s:Symbol)
        WHERE s.project_id = $pid
           OR EXISTS { MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(:File)-[:DEFINES]->(s) }
        RETURN s.name as name, 
               s.file_path as file_path, 
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
               COALESCE(ts.summary, "") as summary,
               COALESCE(ts.community_id, 0) as community_id
        LIMIT 5000
        """
        return self.neo4j.query(query, {"pid": project_id})
    
    # --- Layer 1: CALLS Graph ---
    
    def _layer1_calls_graph(
        self,
        symbol: Dict,
        all_tests: List[Dict]
    ) -> List[Tuple[Dict, float]]:
        """Find tests via CALLS_PRODUCT graph relationship (test→symbol direction)."""
        symbol_name = symbol.get("name", "")
        symbol_file = symbol.get("file_path", "")
        
        query = """
        MATCH (ts:TestSymbol)-[:CALLS_PRODUCT]->(s:Symbol {name: $name, file_path: $file_path})
        RETURN ts.name as name, ts.file_path as file_path
        """
        results = self.neo4j.query(query, {"name": symbol_name, "file_path": symbol_file})
        
        test_map = {t["file_path"]: t for t in all_tests}
        candidates = []
        
        for r in results:
            test_file = r.get("file_path")
            if test_file in test_map:
                candidates.append((test_map[test_file], 0.88))
        
        return candidates
    
    # --- Layer 2: Filename Heuristics ---
    
    def _layer2_filename_heuristics(
        self,
        symbol: Dict,
        all_tests: List[Dict]
    ) -> List[Tuple[Dict, float]]:
        """Match via filename patterns."""
        import os
        symbol_file = symbol.get("file_path", "")
        
        if not symbol_file:
            return []
        
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
                if test_base in [symbol_base + ".test", symbol_base + ".spec"]:
                    confidence = 0.85
            elif symbol_ext == ".py":
                if test_base in [symbol_base + "_test", "test_" + symbol_base]:
                    confidence = 0.85
            
            if confidence > 0:
                test_dir = os.path.dirname(test_file)
                if test_dir == symbol_dir:
                    confidence += 0.1
                candidates.append((test, min(confidence, 0.95)))
        
        return candidates
    
    # --- Layer 3: Community Co-location ---
    
    def _layer3_community(
        self,
        symbol: Dict,
        all_tests: List[Dict]
    ) -> List[Tuple[Dict, float]]:
        """Filter by Leiden community."""
        community_id = symbol.get("community_id", 0)
        
        if community_id == 0:
            return []
        
        candidates = []
        
        for test in all_tests:
            test_community = test.get("test_community_id", 0)
            if test_community == community_id:
                candidates.append((test, 0.70))
        
        return candidates
    
    # --- Candidate Building ---
    
    def _build_candidates(
        self,
        product_symbols: List[Dict],
        all_tests: List[Dict]
    ) -> List[Dict]:
        """Build candidate pairs using all layers."""
        import logging
        logger = logging.getLogger(__name__)
        
        test_map = {t["file_path"]: t for t in all_tests}
        candidates = []
        max_per_symbol = 50  # Generate more candidates per symbol
        
        logger.info(f"Building candidates: {len(product_symbols)} symbols, {len(all_tests)} tests")
        
        for symbol in product_symbols:
            symbol_name = symbol.get("name", "")
            symbol_file = symbol.get("file_path", "")
            
            if not symbol_name or not symbol_file:
                continue
            
            layer_candidates = []
            
            # Layer 1: CALLS graph
            l1 = self._layer1_calls_graph(symbol, all_tests)
            layer_candidates.extend(l1)
            
            # Layer 2: Filename heuristics
            l2 = self._layer2_filename_heuristics(symbol, all_tests)
            layer_candidates.extend(l2)
            
            # Layer 3: Leiden community
            l3 = self._layer3_community(symbol, all_tests)
            layer_candidates.extend(l3)
            
            # Initialize test_confidence from layer candidates
            test_confidence = {}
            for test, conf in layer_candidates:
                test_file = test.get("file_path", "")
                if test_file and test_file not in test_confidence:
                    test_confidence[test_file] = conf
                elif test_file in test_confidence:
                    test_confidence[test_file] = max(test_confidence[test_file], conf)
            
            # If no heuristic candidates, generate candidates from ALL tests (embedding-based)
            if not test_confidence:
                # Fallback: use TOP tests for embedding-based matching
                # Too many tests = too many comparisons
                threshold_to_pass = self.config.heuristic_threshold
                for test in all_tests[:200]:  # Limit to 200 for performance
                    test_file = test.get("file_path", "")
                    if test_file:
                        test_confidence[test_file] = threshold_to_pass
                
                logger.info(f"No heuristic matches for {symbol_name}, using embedding fallback with {len(test_confidence)} candidates")
            
            sorted_tests = sorted(
                test_confidence.items(),
                key=lambda x: x[1],
                reverse=True
            )[:max_per_symbol]
            
            for test_file, heuristic_conf in sorted_tests:
                if test_file in test_map:
                    test = test_map[test_file]
                    candidates.append({
                        "symbol_name": symbol_name,
                        "symbol_file": symbol_file,
                        "symbol_summary": symbol.get("summary", ""),
                        "test_name": test.get("name", ""),
                        "test_file": test_file,
                        "test_summary": test.get("summary", ""),
                        "heuristic_confidence": heuristic_conf,
                    })
        
        return candidates
    
    # --- Siamese Matching ---
    
    def _match_with_siamese(
        self,
        candidates: List[Dict],
        threshold: float = None
    ) -> List[Match]:
        """Match candidates using Siamese embeddings with max fusion."""
        if not candidates:
            return []
        
        if threshold is None:
            threshold = self.config.siamese_threshold
        
        siamese_threshold = self.config.siamese_threshold
        mpnet_threshold = self.config.mpnet_threshold
        
        symbol_texts = [c["symbol_summary"] for c in candidates]
        test_texts = [c["test_summary"] for c in candidates]
        
        siamese_embeddings = self.embedder.embed_batch(symbol_texts, model="siamese")
        test_siamese_embeddings = self.embedder.embed_batch(test_texts, model="siamese")
        
        if self.config.fallback_to_mpnet:
            mpnet_embeddings = self.embedder.embed_batch(symbol_texts, model="mpnet")
            test_mpnet_embeddings = self.embedder.embed_batch(test_texts, model="mpnet")
        else:
            mpnet_embeddings = None
            test_mpnet_embeddings = None
        
        matches = []
        
        for i, candidate in enumerate(candidates):
            heuristic_conf = candidate.get("heuristic_confidence", 0.0)
            
            # CASCADED: Heuristic must pass first before computing embeddings
            heuristic_threshold = self.config.heuristic_threshold
            
            # Initialize for else case
            siamese_conf = 0.0
            mpnet_conf = 0.0
            final_conf = 0.0
            model_used = "none"
            reasoning = ""
            
            if heuristic_conf >= heuristic_threshold:
                # Heuristic matched - verify with embeddings
                sym_emb = siamese_embeddings[i] if i < len(siamese_embeddings) else None
                test_embs = test_siamese_embeddings
                
                if sym_emb is not None and test_embs is not None:
                    sim_scores = self.embedder.compute_similarity(sym_emb, test_embs, top_k=5)
                    if sim_scores:
                        best_idx, siamese_conf = sim_scores[0]
                
                if mpnet_embeddings is not None and test_mpnet_embeddings is not None:
                    sym_emb_mpnet = mpnet_embeddings[i]
                    test_embs_mpnet = test_mpnet_embeddings
                    if sym_emb_mpnet is not None and test_embs_mpnet is not None:
                        sim_scores_mpnet = self.embedder.compute_similarity(sym_emb_mpnet, test_embs_mpnet, top_k=5)
                        if sim_scores_mpnet:
                            best_idx_mpnet, mpnet_conf = sim_scores_mpnet[0]
                
                # Both embeddings must also pass threshold for final acceptance
                embedding_pass = siamese_conf >= self.config.siamese_threshold or mpnet_conf >= self.config.mpnet_threshold
                
                if not embedding_pass:
                    # Embeddings didn't verify - reject even though heuristic matched
                    reasoning = f"Heuristic: {heuristic_conf:.2f} PASS, Siamese: {siamese_conf:.2f} FAIL, MPNet: {mpnet_conf:.2f} FAIL"
                    continue
                
                final_conf = max(siamese_conf, mpnet_conf, heuristic_conf)
                model_used = "siamese" if siamese_conf >= mpnet_conf else "mpnet"
                reasoning = f"Siamese: {siamese_conf:.2f}, MPNet: {mpnet_conf:.2f}, Heuristic: {heuristic_conf:.2f}"
            else:
                # Heuristic didn't pass threshold - reject early
                continue
            
            if final_conf < self.config.siamese_threshold:
                continue
            
            test_name = candidate["test_name"]
            test_file = candidate["test_file"]
            test_summary = candidate["test_summary"]
            
            match = Match(
                symbol_name=candidate["symbol_name"],
                symbol_file=candidate["symbol_file"],
                symbol_summary=candidate["symbol_summary"],
                test_name=test_name,
                test_file=test_file,
                test_summary=test_summary,
                confidence=final_conf,
                siamese_confidence=siamese_conf,
                mpnet_confidence=mpnet_conf,
                heuristic_confidence=heuristic_conf,
                source=model_used,
                reasoning=reasoning
            )
            matches.append(match)
        
        return matches
    
    # --- Edge Creation ---
    
    def create_edges(
        self,
        matches: List[Match],
        project_id: int,
        model: str = "siamese"
    ) -> int:
        """Create EVIDENCE edges in Neo4j."""
        if not matches:
            return 0
        
        edges = [
            {
                "symbol_name": m.symbol_name,
                "symbol_file": m.symbol_file,
                "test_name": m.test_name,
                "test_file": m.test_file,
                "siamese_confidence": m.siamese_confidence,
                "mpnet_confidence": m.mpnet_confidence,
                "heuristic_confidence": m.heuristic_confidence,
                "final_confidence": m.confidence,
                "reasoning": m.reasoning,
            }
            for m in matches
        ]
        
        return self.neo4j.bulk_add_siamese_edges(edges, model=model)
    
    # --- Two-Layer: Siamese + Heuristic ---
    
    def _match_siamese_with_heuristic(
        self,
        symbols: List[Dict],
        tests: List[Dict],
        siamese_threshold: float = 0.5,
        heuristic_threshold: float = 0.75,
        top_k: int = 50
    ) -> List[Match]:
        """Two-layer: Siamese >= 0.5, THEN Heuristic >= 0.8 filter."""
        import logging
        import os
        logger = logging.getLogger(__name__)
        
        if not symbols or not tests:
            return []
        
        logger.info(f"Two-layer: Siamese@({siamese_threshold}) + Heuristic@({heuristic_threshold})")
        
        test_map = {t["file_path"]: t for t in tests}
        
        symbol_texts = [f"{s.get('name', '')} {s.get('summary', '')}" for s in symbols]
        test_texts = [f"{t.get('name', '')} {t.get('summary', '')}" for t in tests]
        
        logger.info(f"Embedding {len(symbol_texts)} symbols with Siamese...")
        symbol_embeddings = self.embedder.embed_batch(symbol_texts, model="siamese", normalize=False)
        
        logger.info(f"Embedding {len(test_texts)} tests with Siamese...")
        test_embeddings = self.embedder.embed_batch(test_texts, model="siamese", normalize=False)
        
        if not symbol_embeddings or not test_embeddings:
            logger.warning("Siamese embeddings failed")
            return []
        
        matched_pairs = {}
        
        logger.info(f"Computing similarity for {len(symbols)} symbols...")
        
        for i, symbol in enumerate(symbols):
            if i > 0 and i % 50 == 0:
                logger.info(f"Processed {i}/{len(symbols)} symbols")
            
            sym_emb = symbol_embeddings[i] if i < len(symbol_embeddings) else None
            if sym_emb is None:
                continue
            
            sym_file = symbol.get("file_path", "")
            sym_name = symbol.get("name", "")
            sym_base = os.path.splitext(os.path.basename(sym_file))[0]
            sym_ext = os.path.splitext(sym_file)[1]
            sym_dir = os.path.dirname(sym_file)
            
            sim_scores = self.embedder.compute_similarity(sym_emb, test_embeddings, top_k=top_k)
            
            for test_idx, siamese_conf in sim_scores:
                if siamese_conf < siamese_threshold:
                    break
                
                if test_idx >= len(tests):
                    continue
                test = tests[test_idx]
                test_file = test.get("file_path", "")
                
                if not test_file or test_file not in test_map:
                    continue
                
                test_base = os.path.splitext(os.path.basename(test_file))[0]
                test_dir = os.path.dirname(test_file)
                
                heuristic_conf = 0.0
                
                if sym_ext in [".ts", ".tsx", ".js", ".jsx"]:
                    if test_base in [sym_base + ".test", sym_base + ".spec"]:
                        heuristic_conf = 0.85
                elif sym_ext == ".py":
                    if test_base in [sym_base + "_test", "test_" + sym_base]:
                        heuristic_conf = 0.85
                
                if not heuristic_conf and sym_dir and test_dir:
                    if sym_dir == test_dir or test_dir.startswith(sym_dir + "/"):
                        heuristic_conf = 0.75
                
                # Tiered OR fusion — any acceptable path creates the edge
                accept = False
                if heuristic_conf >= 0.85:
                    accept = True  # Strong heuristic alone
                elif siamese_conf >= 0.5 and heuristic_conf >= 0.5:
                    accept = True  # Moderate embedding + weak heuristic
                elif siamese_conf >= 0.4 and heuristic_conf >= 0.85:
                    accept = True  # Weak embedding + strong heuristic
                
                if not accept:
                    continue
                
                final_conf = max(siamese_conf, heuristic_conf)
                source = "heuristic" if heuristic_conf >= siamese_conf else "siamese"
                reasoning = f"Siamese: {siamese_conf:.2f}, Heuristic: {heuristic_conf:.2f}"
                
                pair_key = (sym_file, test_file)
                matched_pairs[pair_key] = Match(
                    symbol_name=sym_name,
                    symbol_file=sym_file,
                    symbol_summary=symbol.get("summary", ""),
                    test_name=test.get("name", ""),
                    test_file=test_file,
                    test_summary=test.get("summary", ""),
                    confidence=final_conf,
                    siamese_confidence=siamese_conf,
                    mpnet_confidence=0.0,
                    heuristic_confidence=heuristic_conf,
                    source=source,
                    reasoning=reasoning
                )
        
        matches = list(matched_pairs.values())
        
        logger.info(f"Two-layer: {len(matches)} matches (Siamese >= {siamese_threshold} AND Heuristic >= {heuristic_threshold})")
        
        return matches
    
    # --- Main Pipeline ---
    
    def map_tests(
        self,
        project_id: int,
        threshold: float = None,
        model: str = "siamese"
    ) -> Generator[Dict, None, None]:
        """Full test mapping pipeline.
        
        Args:
            project_id: The SQL project ID
            threshold: Minimum confidence (default: config threshold)
            model: Model type for edge creation
        
        Yields:
            Dict with mapping progress and results
        """
        logger.info(f"Starting SiameseMapper for project {project_id}")
        
        yield {"event": "reasoning", "data": "Fetching unmapped symbols (no existing EVIDENCE)..."}
        symbols = self._get_unmapped_symbols(project_id)
        yield {"event": "progress", "data": f"Found {len(symbols)} total symbols"}
        
        if not symbols:
            yield {"event": "status", "data": {"status": "NO_SYMBOLS", "message": "No unmapped symbols found"}}
            return
        
        yield {"event": "reasoning", "data": "Fetching test symbols..."}
        all_tests = self._get_all_tests(project_id)
        yield {"event": "progress", "data": f"Found {len(all_tests)} test symbols"}
        
        if not all_tests:
            yield {"event": "status", "data": {"status": "NO_TESTS", "message": "No test symbols found"}}
            return
        
        yield {"event": "reasoning", "data": "Two-layer: Siamese + Heuristic matching..."}
        matches = self._match_siamese_with_heuristic(
            symbols, all_tests,
            siamese_threshold=threshold or self.config.siamese_threshold,
            heuristic_threshold=self.config.heuristic_threshold
        )
        yield {"event": "progress", "data": f"Two-layer found {len(matches)} matches"}
        
        if not matches:
            yield {"event": "status", "data": {"status": "NO_MATCHES", "message": "No matches found"}}
            return
        
        yield {"event": "reasoning", "data": "Creating EVIDENCE edges..."}
        edges_created = self.create_edges(matches, project_id, model=model)
        yield {"event": "progress", "data": f"Created {edges_created} edges in Neo4j"}
        
        yield {
            "event": "status",
            "data": {
                "status": "COMPLETED",
                "symbols": len(symbols),
                "tests": len(all_tests),
                "candidates": len(matches),
                "matches": len(matches),
                "edges": edges_created,
                "model": model
            }
        }
    
    def generate_candidates(self, project_id: int) -> List[Dict]:
        """Generate candidate test mappings (for streaming pipeline)."""
        symbols = self._get_unmapped_symbols(project_id)
        all_tests = self._get_all_tests(project_id)
        return self._build_candidates(symbols, all_tests)