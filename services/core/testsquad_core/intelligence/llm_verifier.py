import json
import logging
from typing import List, Dict, Optional
from testsquad_core.graph.client import Neo4jClient
from testsquad_core.intelligence.registry import llm_registry

logger = logging.getLogger(__name__)


class LLMVerifier:
    """LLM-based verification of borderline candidate pairs.

    Two modes:
    1. Test intent extraction (one call per test file)
    2. Candidate pair verification (batch 30 pairs per call)
    """

    def __init__(
        self,
        neo4j: Neo4jClient,
        provider_name: str = "cloudflare",
        model_name: str = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    ):
        self.neo4j = neo4j
        self.provider_name = provider_name
        self.model_name = model_name

    def extract_test_intents(
        self,
        project_id: int,
        batch_size: int = 30
    ) -> List[Dict]:
        """Extract structured intents for all test files (one LLM call per file)."""
        test_files = self.neo4j.query("""
        MATCH (ts:TestSymbol {project_id: $pid})
        RETURN DISTINCT ts.file_path as file_path,
               collect({name: ts.name, summary: coalesce(ts.summary, ts.name)}) as tests
        """, {"pid": project_id})

        intents = []
        provider = llm_registry.get_client(self.provider_name)
        if provider is None:
            logger.warning(f"LLM provider {self.provider_name} not available")
            return intents

        for i, tf in enumerate(test_files):
            tests_json = json.dumps(tf["tests"], indent=2)
            prompt = f"""Extract test intent from each test function in this file.

File: {tf['file_path']}
Tests:
{tests_json}

For each test, identify:
1. Which methods/functions does it call or exercise?
2. What assertion patterns does it use?
3. What is the test scenario (happy path, error, edge case)?

Return JSON array:
[{{"function_name": "...", "methods_under_test": ["..."], "assertions": ["..."], "scenario": "..."}}]
"""
            try:
                response = provider.complete(prompt, model=self.model_name, max_tokens=2048)
                content = response.content
                if isinstance(content, str):
                    content = content.strip()
                    if content.startswith("```"):
                        content = content.split("\n", 1)[-1]
                        content = content.rsplit("```", 1)[0]
                    content = json.loads(content)
                for item in content:
                    item["test_file"] = tf["file_path"]
                    intents.append(item)
            except Exception as e:
                logger.warning(f"LLM intent extraction failed for {tf['file_path']}: {e}")

            if (i + 1) % batch_size == 0:
                logger.info(f"Extracted intents for {i + 1}/{len(test_files)} files")

        return intents

    def verify_pairs(
        self,
        candidates: List[Dict],
        batch_size: int = 30
    ) -> List[Dict]:
        """Verify candidate pairs using LLM.

        Each candidate should have:
            - symbol_name, symbol_code (or signature)
            - test_name, test_code (or signature)

        Returns candidates with 'llm_verification' score added (0.0, 0.5, or 1.0).
        """
        if not candidates:
            return []

        provider = llm_registry.get_client(self.provider_name)
        if provider is None:
            logger.warning(f"LLM provider {self.provider_name} not available")
            for c in candidates:
                c["llm_verification"] = 0.0
            return candidates

        for i in range(0, len(candidates), batch_size):
            batch = candidates[i:i + batch_size]

            pairs_json = []
            for j, c in enumerate(batch):
                sym_code = c.get("symbol_code") or c.get("symbol_name", "")
                test_code = c.get("test_code") or c.get("test_name", "")
                pairs_json.append({
                    "id": j,
                    "method": str(sym_code)[:500],
                    "test": str(test_code)[:500]
                })

            prompt = f"""For each {{method, test}} pair, answer YES or NO:
Does the test exercise this method?
(The test must call the method and assert on its behavior --
NOT just import the module containing the method.)

Return JSON array:
[{{"id": 0, "answer": "YES", "confidence": 5}}]
where confidence is 1-5 (5 = very confident).

Pairs:
{json.dumps(pairs_json, indent=2)}
"""
            try:
                response = provider.complete(prompt, model=self.model_name, max_tokens=512)
                content = response.content
                if isinstance(content, str):
                    content = content.strip()
                    if content.startswith("```"):
                        content = content.split("\n", 1)[-1]
                        content = content.rsplit("```", 1)[0]
                    content = json.loads(content)

                for result in content:
                    idx = result.get("id")
                    if idx is not None and idx < len(batch):
                        answer = result.get("answer", "NO")
                        conf = result.get("confidence", 1)
                        batch[idx]["llm_verification"] = (conf / 5.0) if answer == "YES" else 0.0

            except Exception as e:
                logger.warning(f"LLM verification failed for batch {i}: {e}")
                for c in batch:
                    c["llm_verification"] = 0.0

            logger.info(f"Verified {min(i + batch_size, len(candidates))}/{len(candidates)} pairs")

        return candidates
