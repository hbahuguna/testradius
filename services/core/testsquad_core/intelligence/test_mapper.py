import json
import asyncio
import logging
from typing import List, Dict, Optional
from testsquad_core.graph.client import Neo4jClient
from testsquad_core.intelligence.providers.base import BaseProvider
from testsquad_shared.intelligence.prompt_registry import prompt_registry
from testsquad_shared.models import LLMRequest

logger = logging.getLogger(__name__)

class TestMapper:
    def __init__(self, neo4j: Neo4jClient, llm_client: BaseProvider, skip_llm: bool = False, use_vector: bool = False):
        self.neo4j = neo4j
        self.llm_client = llm_client
        self.skip_llm = skip_llm
        self.use_vector = use_vector

    async def map_tests(self, project_id: int, model_name: str):
        """Streaming version of test mapping with batching to avoid timeouts."""
        logger.info(f"Starting Test Mapping for project {project_id}...")
        
        # 0. Deterministic Heuristic Tiers (0 LLM Cost)
        self.apply_baseline_automapping(project_id)
        yield "Baseline naming-based mapping complete."
        
        self.apply_subword_alignment(project_id)
        yield "Sub-word heuristic alignment complete."
        
        self.apply_import_graph_matching(project_id)
        yield "Import graph matching complete."
        
        self.apply_directory_colocation(project_id)
        yield "Directory colocation matching complete."
        
        self.apply_test_call_matching(project_id)
        yield "Test call graph matching complete."
        
        self.propagate_neighborhood_mappings(project_id)
        yield "Structural neighborhood propagation complete."
        
        # Optional: Vector Matching
        if self.use_vector:
            try:
                from testsquad_core.intelligence.vector_mapper import VectorMapper
                from testsquad_core.intelligence.embedder import Embedder
                embedder = Embedder()
                embedder.load_model()
                vector_mapper = VectorMapper(self.neo4j, embedder)
                vector_mapper.apply_vector_matching(project_id)
                yield "Vector similarity matching complete."
            except Exception as e:
                logger.warning(f"Vector matching failed: {e}")
                yield f"Vector matching skipped: {e}"
        
        if self.skip_llm:
            yield "Skipping LLM (skip_llm=True). Heuristic mapping complete."
            return
        
        # 1. Semantic Reconciliation (LLM Fallback)
        if not model_name:
            yield "Skipping LLM (no model selected). Heuristic mapping complete."
            return
            
        yield "Starting semantic reconciliation with AI..."
        product_query = """
        MATCH (p:Project {sql_id: $pid})-[*1..2]->(s:Symbol)
        RETURN s.name as name, s.file_path as file_path, s.type as type, COALESCE(s.summary, "") as summary, s.community_id as community_id
        LIMIT 5000
        """
        all_product_symbols = self.neo4j.query(product_query, {"pid": project_id})
        
        # 2. Fetch Automation Test Symbols
        test_query = """
        MATCH (p:Project {sql_id: $pid})-[*1..2]->(ts:TestSymbol)
        RETURN ts.name as name, ts.file_path as file_path, ts.test_type as type
        LIMIT 2000
        """
        test_symbols = self.neo4j.query(test_query, {"pid": project_id})
        
        if not all_product_symbols or not test_symbols:
            yield "Not enough data (symbols/tests) to map."
            return

        yield f"Discovered {len(all_product_symbols)} product symbols and {len(test_symbols)} automation tests."

        # 3. Batch Processing by Community (for macro-level LLM context)
        BATCH_SIZE = 100
        total_mapped = 0
        semaphore = asyncio.Semaphore(5)  # Reduced concurrency to avoid rate limits
        
        community_groups = {}
        unassigned = []
        for sym in all_product_symbols:
            cid = sym.get("community_id")
            if cid is not None:
                if cid not in community_groups:
                    community_groups[cid] = []
                community_groups[cid].append(sym)
            else:
                unassigned.append(sym)
                
        product_batches = []
        # Add communities as distinct batches (split if too large)
        for cid, syms in community_groups.items():
            for i in range(0, len(syms), BATCH_SIZE):
                product_batches.append(syms[i : i + BATCH_SIZE])
                
        # Add unassigned
        for i in range(0, len(unassigned), BATCH_SIZE):
            product_batches.append(unassigned[i : i + BATCH_SIZE])
            
        yield f"Processing {len(product_batches)} macro-level community batches concurrently..."

        async def process_batch(batch, batch_idx):
            try:
                async with semaphore:
                    # Dynamic Filtering: Only send tests with name/path relevance to this product batch
                    relevant_tests = self._get_relevant_tests(batch, test_symbols)
                    
                    # Multimodal Context: Fetch documentation mentioning these symbols
                    docs_context = self._get_relevant_docs(batch)
                    
                    prompt_data = prompt_registry.get_prompt(
                        "test_mapper",
                        sum_symbols=batch,
                        test_symbols=relevant_tests
                    )
                    
                    if docs_context:
                        prompt_data["content"] += "\n\n" + docs_context
                    
                    # 3.5 Retry Logic for LLM calls with hard timeout
                    MAX_RETRIES = 3
                    response = None
                    for attempt in range(MAX_RETRIES):
                        try:
                            logger.info(f"Batch {batch_idx}: Starting LLM call (Attempt {attempt+1})...")
                            response = await asyncio.wait_for(
                                self.llm_client.complete(LLMRequest(
                                    provider_name=self.llm_client.__class__.__name__.replace("Provider", ""),
                                    model_name=model_name,
                                    prompt=prompt_data["content"],
                                    max_tokens=4096,
                                    temperature=0.0
                                )),
                                timeout=120  # 2 minute timeout per attempt
                            )
                            if response and response.content and not response.content.startswith("Error:"):
                                break
                            
                            wait_time = 5 * (attempt + 1)
                            logger.warning(f"Batch {batch_idx}: LLM returned error or empty, retrying in {wait_time}s...")
                            await asyncio.sleep(wait_time)
                        except asyncio.TimeoutError:
                            logger.warning(f"Batch {batch_idx}: LLM call timed out (Attempt {attempt+1})")
                            if attempt == MAX_RETRIES - 1:
                                return 0
                            await asyncio.sleep(5)
                        except Exception as e:
                            logger.error(f"Batch {batch_idx}: LLM call failed with {type(e).__name__}: {e}")
                            if attempt == MAX_RETRIES - 1:
                                break
                            await asyncio.sleep(5 * (attempt + 1))
                    
                    if not response or response.content.startswith("Error:"):
                        logger.warning(f"Batch {batch_idx}: Failed all retries or returned error.")
                        return 0
                        
                    content = response.content
                    logger.info(f"Batch {batch_idx}: LLM responded. Parsing results...")
                    
                    if "```json" in content:
                        content = content.split("```json")[1].split("```")[0].strip()
                    elif "```" in content:
                        content = content.split("```")[1].split("```")[0].strip()
                    
                    # Cleanup common JSON issues
                    content = content.strip()
                    if not content.endswith("]"):
                        if "}" in content:
                            content = content[:content.rfind("}")+1] + "]"
                    
                    try:
                        mappings = json.loads(content)
                    except Exception as e:
                        logger.error(f"Batch {batch_idx}: JSON Parse Error: {e}")
                        return 0
                    
                    # 4. Save batch mappings to Neo4j (Optimized with UNWIND)
                    valid_mappings = []
                    for m in mappings:
                        if all(k in m for k in ["product_symbol_name", "product_file_path", "test_symbol_name", "test_file_path"]):
                            valid_mappings.append({
                                "p_name": m["product_symbol_name"],
                                "p_path": m["product_file_path"],
                                "t_name": m["test_symbol_name"],
                                "t_path": m["test_file_path"],
                                "conf": m.get("confidence", 0.0),
                                "reason": m.get("reasoning", ""),
                                "model": model_name
                            })

                    if valid_mappings:
                        logger.info(f"Batch {batch_idx}: Saving {len(valid_mappings)} mappings to Neo4j...")
                        self.neo4j.query("""
                        UNWIND $mappings as m
                        MATCH (s:Symbol {name: m.p_name, file_path: m.p_path})
                        MATCH (ts:TestSymbol {name: m.t_name, file_path: m.t_path})
                        MERGE (s)-[r:EVIDENCE]->(ts)
                        SET r.confidence = m.conf, r.reasoning = m.reason, r.model = m.model
                        """, {"mappings": valid_mappings})
                    
                    return len(valid_mappings)
            except Exception as e:
                logger.error(f"Critical error in process_batch {batch_idx}: {e}")
            return 0

        # Execute parallel mapping
        batch_tasks = [process_batch(batch, i) for i, batch in enumerate(product_batches)]
        
        completed_batches = 0
        for task_coro in asyncio.as_completed(batch_tasks):
            mapped_count = await task_coro
            total_mapped += mapped_count
            completed_batches += 1
            yield f"Progress: {completed_batches}/{len(product_batches)} batches finished. Mapped {total_mapped} total symbols so far..."

        yield f"Successfully paired {total_mapped} functional paths across the codebase rift!"

    def apply_baseline_automapping(self, project_id: int):
        """Perform high-confidence mapping based on filename matching (X.ts -> X.test.ts)."""
        logger.info(f"Applying Baseline Automapping for project {project_id}...")
        
        # This query finds symbols and tests that share the same base filename
        # It handles .ts, .tsx, .py, .js, .jsx and strips .test, .spec, _test, _spec suffixes
        query = """
        MATCH (p:Project {sql_id: $pid})-[*1..2]->(s:Symbol)
        MATCH (p)-[*1..2]->(ts:TestSymbol)
        WHERE 
            // Exact same filename (rare for product/test but possible if in different dirs)
            s.file_path = ts.file_path 
            OR 
            // ts.file_path ends with .test.EXT or .spec.EXT where EXT matches s.file_path extension
            (
                (ts.file_path ENDS WITH ".test.ts" AND s.file_path = REPLACE(ts.file_path, ".test.ts", ".ts")) OR
                (ts.file_path ENDS WITH ".spec.ts" AND s.file_path = REPLACE(ts.file_path, ".spec.ts", ".ts")) OR
                (ts.file_path ENDS WITH ".test.tsx" AND s.file_path = REPLACE(ts.file_path, ".test.tsx", ".tsx")) OR
                (ts.file_path ENDS WITH ".spec.tsx" AND s.file_path = REPLACE(ts.file_path, ".spec.tsx", ".tsx")) OR
                (ts.file_path ENDS WITH ".test.js" AND s.file_path = REPLACE(ts.file_path, ".test.js", ".js")) OR
                (ts.file_path ENDS WITH ".spec.js" AND s.file_path = REPLACE(ts.file_path, ".spec.js", ".js")) OR
                (ts.file_path ENDS WITH "_test.py" AND s.file_path = REPLACE(ts.file_path, "_test.py", ".py")) OR
                (ts.file_path ENDS WITH "test_" + last(split(s.file_path, "/")) AND ts.file_path CONTAINS "/test_")
            )
        MERGE (s)-[r:EVIDENCE]->(ts)
        ON CREATE SET 
            r.confidence = 0.95, 
            r.reasoning = "Automated baseline mapping based on filename match", 
            r.model = "baseline_heuristic"
        """
        self.neo4j.query(query, {"pid": project_id})
        logger.info("Baseline Automapping complete.")

    def apply_subword_alignment(self, project_id: int):
        """Token-based subword alignment for high-recall without LLM costs."""
        logger.info(f"Applying Sub-word Alignment for project {project_id}...")
        
        symbols = self.neo4j.query("""
            MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(:File)-[:DEFINES]->(s:Symbol)
            RETURN s.name as name, s.file_path as file_path
        """, {"pid": project_id})
        
        tests = self.neo4j.query("""
            MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(:TestFile)-[:DEFINES]->(ts:TestSymbol)
            RETURN ts.name as name, ts.file_path as file_path
        """, {"pid": project_id})
        
        if not symbols or not tests:
            return
        
        import re
        
        def tokenize(name: str) -> set:
            tokens = re.findall(r'[a-zA-Z0-9]+', name.lower())
            return {t for t in tokens if len(t) > 2}
        
        mappings = []
        for s in symbols:
            s_tokens = tokenize(s["name"])
            if not s_tokens:
                continue
            
            for ts in tests:
                ts_tokens = tokenize(ts["name"])
                if not ts_tokens:
                    continue
                
                intersection = s_tokens & ts_tokens
                union = s_tokens | ts_tokens
                
                if intersection and union:
                    jaccard = len(intersection) / len(union)
                    if jaccard >= 0.3:
                        mappings.append({
                            "symbol": s,
                            "test": ts,
                            "confidence": jaccard,
                            "reason": f"Subword alignment: {len(intersection)}/{len(union)} tokens"
                        })
        
        for m in mappings:
            self.neo4j.query("""
                MATCH (s:Symbol {name: $sname, file_path: $sfpath})
                MATCH (ts:TestSymbol {name: $tname, file_path: $tfpath})
                MERGE (s)-[r:EVIDENCE]->(ts)
                ON CREATE SET r.confidence = $conf, r.reasoning = $reason, r.model = 'subword_alignment'
            """, {
                "sname": m["symbol"]["name"],
                "sfpath": m["symbol"]["file_path"],
                "tname": m["test"]["name"],
                "tfpath": m["test"]["file_path"],
                "conf": m["confidence"],
                "reason": m["reason"]
            })
        
        logger.info(f"Sub-word Alignment complete. {len(mappings)} mappings created.")

    def apply_import_graph_matching(self, project_id: int):
        """Token-based similarity mapping for high-recall without LLM costs."""
        logger.info(f"Applying Sub-word Alignment for project {project_id}...")
        
        # Fetch all symbols and tests
        symbols = self.neo4j.query("""
            MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(:File)-[:DEFINES]->(s:Symbol)
            RETURN s.name as name, s.file_path as file_path
        """, {"pid": project_id})
        
        tests = self.neo4j.query("""
            MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(:TestFile)-[:DEFINES]->(ts:TestSymbol)
            RETURN ts.name as name, ts.file_path as file_path
        """, {"pid": project_id})
        
        if not symbols or not tests: return

        def tokenize(name: str) -> set:
            import re
            # Split by camelCase, snake_case, and non-alphas
            tokens = re.findall(r'[a-zA-Z0-9]+', name.lower())
            # Filter short tokens
            return {t for t in tokens if len(t) > 2}

        mappings = []
        for s in symbols:
            s_tokens = tokenize(s["name"])
            if not s_tokens: continue
            
            for ts in tests:
                ts_tokens = tokenize(ts["name"])
                if not ts_tokens: continue
                
                # Jaccard similarity or simple overlap
                intersection = s_tokens.intersection(ts_tokens)
                if len(intersection) >= 2 or (len(s_tokens) == 1 and len(intersection) == 1):
                    mappings.append({
                        "p_name": s["name"], "p_path": s["file_path"],
                        "t_name": ts["name"], "t_path": ts["file_path"],
                        "conf": 0.85,
                        "reason": f"Sub-word overlap detected: {list(intersection)}"
                    })

        if mappings:
            # Batch save
            self.neo4j.query("""
            UNWIND $mappings as m
            MATCH (p:Project {sql_id: toInteger($pid)})
            MATCH (p)-[:CONTAINS]->(:File)-[:DEFINES]->(s:Symbol {name: m.p_name, file_path: m.p_path})
            MATCH (p)-[:CONTAINS]->(:TestFile)-[:DEFINES]->(ts:TestSymbol {name: m.t_name, file_path: m.t_path})
            MERGE (s)-[r:EVIDENCE]->(ts)
            ON CREATE SET r.confidence = m.conf, r.reasoning = m.reason, r.model = 'subword_alignment'
            """, {"pid": project_id, "mappings": mappings[:5000]})

    def propagate_neighborhood_mappings(self, project_id: int):
        """Propagates test associations within Leiden communities."""
        logger.info(f"Propagating neighborhood mappings for project {project_id}...")
        query = """
        MATCH (p:Project {sql_id: toInteger($pid)})
        MATCH (p)-[:CONTAINS]->(:File)-[:DEFINES]->(s1:Symbol)-[:EVIDENCE]->(ts:TestSymbol)
        MATCH (p)-[:CONTAINS]->(:File)-[:DEFINES]->(s2:Symbol)
        WHERE s1 <> s2 
          AND s1.community_id = s2.community_id 
          AND s1.community_id IS NOT NULL
          AND NOT (s2)-[:EVIDENCE]->(ts)
        MERGE (s2)-[r:EVIDENCE]->(ts)
        ON CREATE SET 
            r.confidence = 0.75, 
            r.reasoning = "Structural sibling propagation (Leiden Community: " + s1.community_id + ")",
            r.model = "neighborhood_propagation"
        """
        self.neo4j.query(query, {"pid": project_id})

    def apply_import_graph_matching(self, project_id: int):
        """Map tests by matching imports - if a test imports a module, link to symbols in that module."""
        logger.info(f"Applying import graph matching for project {project_id}...")
        
        query = """
        MATCH (p:Project {sql_id: toInteger($pid)})
        MATCH (p)-[:CONTAINS]->(:TestFile)-[:DEFINES]->(ts:TestSymbol)-[:IMPORTS]->(m:Module)
        MATCH (p)-[:CONTAINS]->(:File)-[:DEFINES]->(s:Symbol)
        WHERE s.file_path CONTAINS m.name OR s.name CONTAINS m.name
        AND NOT (s)-[:EVIDENCE]->(ts)
        MERGE (s)-[r:EVIDENCE]->(ts)
        ON CREATE SET 
            r.confidence = 0.90, 
            r.reasoning = "Import graph matching (module: " + m.name + ")",
            r.model = "import_graph"
        """
        self.neo4j.query(query, {"pid": project_id})
        logger.info("Import graph matching complete.")

    def apply_directory_colocation(self, project_id: int):
        """Map tests to symbols in the same directory (shared module path)."""
        logger.info(f"Applying directory colocation matching for project {project_id}...")
        
        query = """
        MATCH (p:Project {sql_id: toInteger($pid)})
        MATCH (p)-[:CONTAINS]->(f:File)-[:DEFINES]->(s:Symbol)
        MATCH (p)-[:CONTAINS]->(tf:TestFile)-[:DEFINES]->(ts:TestSymbol)
        WHERE 
            f.path CONTAINS split(tf.path, '/test')[0] + '/test' OR
            f.path CONTAINS split(tf.path, '/spec')[0] + '/spec' OR
            f.path CONTAINS split(tf.path, '/__tests__')[0] + '/__tests__'
        AND NOT (s)-[:EVIDENCE]->(ts)
        MERGE (s)-[r:EVIDENCE]->(ts)
        ON CREATE SET 
            r.confidence = 0.80, 
            r.reasoning = "Directory colocation (shared module path)",
            r.model = "directory_colocation"
        """
        self.neo4j.query(query, {"pid": project_id})
        logger.info("Directory colocation matching complete.")

    def apply_test_call_matching(self, project_id: int):
        """Map tests by analyzing what product code they call - use CALLS_PRODUCT relationships."""
        logger.info(f"Applying test call graph matching for project {project_id}...")
        
        query = """
        MATCH (p:Project {sql_id: toInteger($pid)})
        MATCH (ts:TestSymbol)-[r:CALLS_PRODUCT]->(s:Symbol)
        WHERE NOT (s)-[:EVIDENCE]->(ts)
        MERGE (s)-[r2:EVIDENCE]->(ts)
        ON CREATE SET 
            r2.confidence = 0.88, 
            r2.reasoning = "Direct test call: test calls product symbol",
            r2.model = "test_call_graph"
        """
        self.neo4j.query(query, {"pid": project_id})
        logger.info("Test call graph matching complete.")

    def _get_relevant_tests(self, product_batch: List[Dict], all_tests: List[Dict]) -> List[Dict]:
        """Heuristic to reduce test symbols in prompt by focusing on relevant directories/keywords."""
        batch_dirs = set()
        batch_keywords = set()
        batch_base_names = set()
        
        for p in product_batch:
            # Extract directory parts, excluding common roots
            path_parts = p["file_path"].lower().split("/")
            filtered_parts = [part for part in path_parts if part not in ["src", "app", "packages", "services", "demo-repo"] and len(part) > 2]
            batch_dirs.update(filtered_parts)
            
            # Extract base name without extension for precise matching
            file_name = path_parts[-1]
            base_name = file_name.split(".")[0]
            if len(base_name) > 3:
                batch_base_names.add(base_name)
            
            batch_keywords.update([k for k in p["name"].lower().replace("-", "_").split("_") if len(k) > 3])

        relevant = []
        for t in all_tests:
            t_path = t["file_path"].lower()
            t_name = t["name"].lower()
            
            # Priority 0: Base name match (e.g. CollisionDetection matches CollisionDetection.test.ts)
            if any(bn in t_path for bn in batch_base_names):
                relevant.append(t)
                continue

            # Priority 1: Direct directory/filename overlap (most precise)
            if any(d in t_path for d in batch_dirs):
                relevant.append(t)
                continue
            # Priority 2: Keyword overlap in test name
            if any(k in t_name for k in batch_keywords):
                relevant.append(t)
                continue
            # Priority 3: Global/E2E/Integration fallbacks
            if any(keyword in t_path for keyword in ["global", "e2e", "integration", "shared"]):
                relevant.append(t)
                continue
        
        # Cap at 300 tests to keep prompt healthy
        return relevant[:300] if len(relevant) > 300 else relevant

    def _get_relevant_docs(self, product_batch: List[Dict]) -> str:
        """Fetch content from Document nodes that mention any symbol in the batch."""
        symbol_names = [s["name"] for s in product_batch]
        if not symbol_names:
            return ""
            
        query = """
        MATCH (d:Document)-[:MENTIONS]->(s:Symbol)
        WHERE s.name IN $names
        RETURN DISTINCT d.path as path, d.content as content
        LIMIT 5
        """
        results = self.neo4j.query(query, {"names": symbol_names})
        
        if not results:
            return ""
            
        doc_texts = ["--- MULTIMODAL DOCUMENTATION CONTEXT ---"]
        for r in results:
            path = r["path"]
            content = r["content"]
            # Keep snippets reasonable
            if len(content) > 5000:
                content = content[:5000] + "\n...[truncated]..."
            doc_texts.append(f"Document: {path}\n{content}")
            
        return "\n\n".join(doc_texts)
