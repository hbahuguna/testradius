import os
import logging
from typing import Generator, Dict
from testsquad_core.graph.client import Neo4jClient
from testsquad_core.intelligence.heuristic_mapper import HeuristicMapper
from testsquad_core.intelligence.cross_encoder import CrossEncoderScorer
from testsquad_core.intelligence.ensemble_fuser import EnsembleFuser
from testsquad_core.intelligence.llm_verifier import LLMVerifier
from testsquad_core.intelligence.active_learner import ActiveLearner
from testsquad_core.intelligence.siamese_mapper import SiameseMapper
from testsquad_core.intelligence.siamese_config import SiameseConfig

logger = logging.getLogger(__name__)


class MappingOrchestrator:
    """Orchestrate the multi-stage ensemble mapping pipeline.

    Stages:
    1. HeuristicMapper (zero-cost, always runs)
    2. SiameseMapper (embedding-based, runs if model available)
    3. CrossEncoder (reranking, runs if model trained)
    4. LLM verification (runs if API available)
    5. EnsembleFuser (always runs after features collected)
    """

    def __init__(self, neo4j: Neo4jClient):
        self.neo4j = neo4j

    def map_all(
        self,
        project_id: int,
        run_siamese: bool = True,
        run_cross_encoder: bool = True,
        run_llm: bool = True
    ) -> Generator[Dict, None, None]:
        """Run the full pipeline."""

        # Stage 1: HeuristicMapper
        yield {"event": "stage", "data": "Stage 1/5: HeuristicMapper"}
        heuristic = HeuristicMapper(self.neo4j)
        for event in heuristic.map_tests(project_id):
            yield event

        # Stage 2: SiameseMapper
        if run_siamese:
            yield {"event": "stage", "data": "Stage 2/5: SiameseMapper"}
            config = SiameseConfig(
                model_path=os.getenv("METHOD2TEST_PATH", ""),
                siamese_threshold=0.5,
                heuristic_threshold=0.75
            )
            siamese = SiameseMapper(neo4j=self.neo4j, config=config)
            for event in siamese.map_tests(project_id):
                yield event

        # Stage 3: CrossEncoder
        if run_cross_encoder:
            yield {"event": "stage", "data": "Stage 3/5: CrossEncoder"}
            try:
                cross_encoder = CrossEncoderScorer()
                candidates = self.neo4j.query("""
                MATCH (s:Symbol)
                WHERE s.project_id = $pid
                  AND NOT EXISTS { MATCH (s)<-[:EVIDENCE]-(:TestSymbol) }
                MATCH (ts:TestSymbol {project_id: $pid})
                WHERE NOT EXISTS { MATCH (ts)-[:EVIDENCE]->(s) }
                RETURN s.name as symbol_name,
                       s.file_path as symbol_file,
                       coalesce(s.summary, s.name) as symbol_code,
                       ts.name as test_name,
                       ts.file_path as test_file,
                       coalesce(ts.summary, ts.name) as test_code
                LIMIT 10000
                """, {"pid": project_id})

                if candidates:
                    yield {"event": "progress", "data": f"Cross-Encoder scoring {len(candidates)} pairs"}
                    reranked = cross_encoder.rerank(candidates, top_k=20)
                    cross_encoder.update_features(reranked)
                    if reranked:
                        edges = self.neo4j.bulk_add_evidence_edges(reranked, source="cross_encoder")
                        yield {"event": "progress", "data": f"Cross-Encoder: {edges} edges"}
            except Exception as e:
                yield {"event": "warning", "data": f"Cross-Encoder failed: {e}"}

        # Stage 4: LLM verification
        if run_llm:
            yield {"event": "stage", "data": "Stage 4/5: LLM Verification"}
            try:
                verifier = LLMVerifier(self.neo4j)
                intents = verifier.extract_test_intents(project_id)
                yield {"event": "progress", "data": f"LLM: {len(intents)} test intents"}
            except Exception as e:
                yield {"event": "warning", "data": f"LLM verification failed: {e}"}

        # Stage 5: EnsembleFuser
        yield {"event": "stage", "data": "Stage 5/5: EnsembleFuser"}
        try:
            fuser = EnsembleFuser()
            pos = self.neo4j.query("""
            MATCH (ts:TestSymbol)-[r:EVIDENCE]->(s:Symbol)
            WHERE r.features IS NOT NULL
              AND (r.confidence >= 0.8 OR r.final_confidence >= 0.8)
            RETURN r.features as features LIMIT 5000
            """)
            neg = self.neo4j.query("""
            MATCH (ts:TestSymbol)-[r:EVIDENCE]->(s:Symbol)
            WHERE r.features IS NOT NULL
              AND (r.confidence < 0.3 OR r.final_confidence < 0.3)
            RETURN r.features as features LIMIT 5000
            """)

            if pos and neg:
                fuser.train(pos, neg)
                yield {"event": "progress", "data": f"Fuser trained on {len(pos)} pos, {len(neg)} neg"}

                to_fuse = self.neo4j.query("""
                MATCH (ts:TestSymbol)-[r:EVIDENCE]->(s:Symbol {project_id: $pid})
                WHERE r.features IS NOT NULL AND r.final_confidence IS NULL
                RETURN elementId(r) as edge_id, r.features as features
                LIMIT 20000
                """, {"pid": project_id})

                for edge in to_fuse:
                    score = fuser.predict(edge["features"])
                    self.neo4j.query("""
                    MATCH (ts:TestSymbol)-[r:EVIDENCE]->(s:Symbol)
                    WHERE elementId(r) = $edge_id
                    SET r.final_confidence = $score
                    """, {"edge_id": edge["edge_id"], "score": round(score, 4)})

                yield {"event": "progress", "data": f"Fuser: {len(to_fuse)} edges updated"}
        except Exception as e:
            yield {"event": "warning", "data": f"Ensemble fusion failed: {e}"}

        yield {"event": "status", "data": {"status": "COMPLETED"}}
