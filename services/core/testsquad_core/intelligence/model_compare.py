import logging
from typing import List, Dict, Optional, Tuple
from testsquad_core.graph.client import Neo4jClient
from testsquad_core.intelligence.siamese_config import SiameseConfig
from testsquad_core.intelligence.siamese_mapper import SiameseMapper
from testsquad_core.intelligence.vector_mapper import VectorMapper
from testsquad_core.intelligence.embedder import Embedder

logger = logging.getLogger(__name__)


class ModelCompare:
    """Compare mapping results from different models.
    
    Compares:
    - Siamese (fine-tuned model)
    - MPNet (sentence-transformers)
    - Vector (BM25/keyword)
    - LLM (LLM-based, if available)
    """
    
    def __init__(
        self,
        neo4j: Neo4jClient,
        config: Optional[SiameseConfig] = None
    ):
        self.neo4j = neo4j
        self.config = config or SiameseConfig()
        self.siamese_mapper = SiameseMapper(neo4j, config=config)
        self.vector_mapper = None
        self.embedder = None
    
    def _init_vector_mapper(self):
        """Lazy init VectorMapper."""
        if self.vector_mapper is None:
            self.embedder = Embedder()
            self.vector_mapper = VectorMapper(self.neo4j, embedder=self.embedder)
    
    def compare_symbol(
        self,
        symbol_name: str,
        symbol_file: str,
        project_id: int,
        top_k: int = 5
    ) -> Dict[str, List[Dict]]:
        """Compare mappings for a single symbol across models.
        
        Returns:
            Dict with keys: siamese, mpnet, vector, each containing list of test candidates
        """
        results = {
            "symbol": {"name": symbol_name, "file": symbol_file},
            "siamese": [],
            "mpnet": [],
            "vector": []
        }
        
        candidates = [
            {
                "symbol_name": symbol_name,
                "symbol_file": symbol_file,
                "symbol_summary": "",
                "test_name": "",
                "test_file": "",
                "test_summary": "",
                "heuristic_confidence": 0.5
            }
        ]
        
        try:
            siamese_matches = self.siamese_mapper._match_with_siamese(
                candidates, 
                threshold=self.config.siamese_threshold
            )
            results["siamese"] = [
                {
                    "test_name": m.test_name,
                    "test_file": m.test_file,
                    "confidence": m.confidence,
                    "siamese_conf": m.siamese_confidence,
                    "mpnet_conf": m.mpnet_confidence
                }
                for m in siamese_matches[:top_k]
            ]
        except Exception as e:
            logger.warning(f"Siamese comparison failed: {e}")
        
        try:
            self._init_vector_mapper()
            vector_matches = self.vector_mapper._match_vectors(
                candidates,
                threshold=0.75
            )
            results["vector"] = [
                {
                    "test_name": m["test_name"],
                    "test_file": m["test_file"],
                    "confidence": m["confidence"]
                }
                for m in vector_matches[:top_k]
            ]
        except Exception as e:
            logger.warning(f"Vector comparison failed: {e}")
        
        return results
    
    def compare_project(
        self,
        project_id: int,
        limit: int = 20,
        model: str = "both"
    ) -> Dict:
        """Compare mappings for entire project.
        
        Returns aggregated comparison stats.
        """
       stats = {
            "project_id": project_id,
            "siamese_total": 0,
            "siamese_threshold_pass": 0,
            "mpnet_total": 0,
            "mpnet_threshold_pass": 0,
            "vector_total": 0,
            "vector_threshold_pass": 0,
            "agreements": 0,
            "disagreements": 0,
            "comparisons": []
        }
        
        try:
            siamese_candidates = self.siamese_mapper.generate_candidates(project_id)
            stats["siamese_total"] = len(siamese_candidates)
            stats["siamese_threshold_pass"] = sum(
                1 for c in siamese_candidates 
                if c.get("heuristic_confidence", 0) >= self.config.siamese_threshold
            )
        except Exception as e:
            logger.warning(f"Siamese project compare failed: {e}")
        
        try:
            self._init_vector_mapper()
            vector_candidates = self.vector_mapper.generate_candidates(project_id)
            stats["vector_total"] = len(vector_candidates)
            stats["vector_threshold_pass"] = sum(
                1 for c in vector_candidates
                if c.get("confidence", 0) >= 0.75
            )
        except Exception as e:
            logger.warning(f"Vector project compare failed: {e}")
        
        return stats
    
    def get_overlap(
        self,
        project_id: int,
        top_k: int = 3
    ) -> Dict:
        """Calculate overlap between Siamese and Vector mappings.
        
        Returns:
            Dict with agreement statistics
        """
        overlap = {
            "project_id": project_id,
            "exact_match_count": 0,
            "top_k_match_count": 0,
            "unique_to_siamese": 0,
            "unique_to_vector": 0,
            "details": []
        }
        
        try:
            self._init_vector_mapper()
            siamese_cands = self.siamese_mapper.generate_candidates(project_id)
            vector_cands = self.vector_mapper.generate_candidates(project_id)
            
            siamese_tests = {
                (c.get("test_name"), c.get("test_file")): c.get("confidence", 0)
                for c in siamese_cands
            }
            vector_tests = {
                (c.get("test_name"), c.get("test_file")): c.get("confidence", 0)
                for c in vector_cands
            }
            
            all_test_keys = set(siamese_tests.keys()) | set(vector_tests.keys())
            
            for test_key in all_test_keys:
                in_siamese = test_key in siamese_tests
                in_vector = test_key in vector_tests
                
                if in_siamese and in_vector:
                    overlap["exact_match_count"] += 1
                elif in_siamese and not in_vector:
                    overlap["unique_to_siamese"] += 1
                elif not in_siamese and in_vector:
                    overlap["unique_to_vector"] += 1
            
            overlap["total_tests"] = len(all_test_keys)
            
        except Exception as e:
            logger.warning(f"Overlap calculation failed: {e}")
        
        return overlap