import json
import logging
from typing import List, Dict, Optional
from testsquad_shared.models import LLMRequest, ProviderConfig
from testsquad_core.intelligence.registry import llm_registry, initialize_standard_providers
from testsquad_core.graph.client import Neo4jClient
from testsquad_shared.intelligence.prompt_registry import prompt_registry
from testsquad_core.intelligence.sentinel import JSONSentinel
from testsquad_core.intelligence.providers.base import BaseProvider
import os

logger = logging.getLogger(__name__)

CLOUDFLARE_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"


class SymbolSummarizer:
    def __init__(self, neo4j: Neo4jClient, llm_client: Optional[BaseProvider] = None,
                 model_name: str = CLOUDFLARE_MODEL, provider_name: str = "Cloudflare"):
        self.neo4j = neo4j
        self.model_name = model_name
        self.provider_name = provider_name
        self.sentinel = JSONSentinel()
        self.llm_client = llm_client

        # Ensure standard providers are initialized if no client passed
        if not self.llm_client:
            initialize_standard_providers()

    async def summarize_all_missing(self, project_id: int, repo_root: Optional[str] = None):
        """Finds all symbols in a project missing a summary and generates them. Yields progress."""
        # 1. Fetch symbols missing summaries (via property OR graph path)
        query = """
        MATCH (s:Symbol)
        WHERE s.summary IS NULL
          AND (s.project_id = $project_id
               OR EXISTS { MATCH (p:Project {sql_id: $project_id})-[:CONTAINS]->(:File)-[:DEFINES]->(s) })
        RETURN s.name as name, s.file_path as file_path, s.type as type, s.start_line as start_line, s.end_line as end_line
        """
        symbols = self.neo4j.query(query, {"project_id": project_id})
        
        if not symbols:
            yield "No symbols missing summaries."
            return

        # Cap total symbols to summarize in one session for speed
        MAX_GLOBAL_SUMMARIES = 10000
        if len(symbols) > MAX_GLOBAL_SUMMARIES:
            yield f"Project has {len(symbols)} symbols. Prioritizing {MAX_GLOBAL_SUMMARIES} for mapping..."
            symbols = symbols[:MAX_GLOBAL_SUMMARIES]

        total = len(symbols)
        yield f"Summarizing {total} symbols..."
        
        if not repo_root:
            repo_root = os.getcwd()

        # 2. Process concurrently with Semaphore
        import asyncio
        semaphore = asyncio.Semaphore(5)  # Limit concurrent LLM batches
        batch_size = 10  # Increased batch size for better efficiency
        processed = 0
        
        async def run_batch(batch_to_proc):
            async with semaphore:
                try:
                    return await self._summarize_batch(batch_to_proc, repo_root)
                except Exception as e:
                    logger.error(f"Summarization batch failed: {e}")
                    return 0

        # Create tasks for all batches
        batch_tasks = [run_batch(symbols[i:i+batch_size]) for i in range(0, total, batch_size)]
        
        # Stream progress as batches complete
        for coro in asyncio.as_completed(batch_tasks):
            count = await coro
            processed += count
            yield f"Summarized {processed}/{total} symbols..."

    async def _summarize_batch(self, batch: List[Dict], repo_root: str) -> int:
        """Generates summaries for a batch of symbols. Returns count of successful summaries."""
        client = self.llm_client or llm_registry.get_client(self.provider_name)
        if not client:
            logger.error(f"LLM Provider {self.provider_name} not available.")
            return 0

        symbol_data = []
        for sym in batch:
            content = self._get_symbol_content(repo_root, sym["file_path"], sym["start_line"], sym["end_line"])
            if content:
                symbol_data.append({
                    "name": sym["name"],
                    "file": sym["file_path"],
                    "content": content
                })

        if not symbol_data:
            return 0

        prompt_data = prompt_registry.get_prompt("summarize_symbol", symbol_data=symbol_data)
        
        request = LLMRequest(
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt=prompt_data["content"],
            max_tokens=prompt_data["metadata"].get("max_tokens", 4096),
            temperature=prompt_data["metadata"].get("temperature", 0.1)
        )

        try:
            response = await client.complete(request)
        except Exception as e:
            logger.error(f"LLM call failed for batch: {e}")
            return 0

        if response.content.startswith("Error:"):
            logger.warning(f"LLM returned error for batch: {response.content[:200]}")
            return 0

        try:
            clean_content = self.sentinel.clean_json_string(response.content)
            summaries = json.loads(clean_content)
        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return 0

        if not isinstance(summaries, list):
            logger.warning(f"LLM response is not a list: {type(summaries)}")
            return 0

        success_count = 0
        for item in summaries:
            name = item.get("name")
            file_path = item.get("file")
            summary = item.get("summary")
            priority = item.get("priority", 5)

            if name and file_path and summary:
                self.neo4j.update_symbol_summary(file_path, name, summary, priority)
                logger.info(f"Updated summary for {name} in {file_path}")
                success_count += 1

        return success_count

    def _get_symbol_content(self, repo_root: Optional[str], file_path: str, start_line: Optional[int], end_line: Optional[int]) -> Optional[str]:
        """Reads the symbol's source code from disk.
        
        If start_line is provided and valid, returns only that section.
        Falls back to entire file if line range is out of bounds.
        Otherwise returns the entire file content.
        """
        try:
            full_path = file_path if os.path.isabs(file_path) else os.path.join(repo_root or "", file_path)
            if not os.path.exists(full_path):
                return None
            
            with open(full_path, "r") as f:
                lines = f.readlines()
            
            if start_line is not None and end_line is not None:
                if start_line <= len(lines):
                    return "".join(lines[start_line-1:end_line])
                return "".join(lines)
            return "".join(lines)
        except Exception as e:
            logger.warning(f"Could not read symbol content for {file_path}: {e}")
            return None

    async def summarize_symbols_for_tests(self, project_id: int, repo_root: Optional[str] = None) -> int:
        """Find test symbols missing summaries and generate them. Returns count.
        
        Groups test symbols by file, reads the whole file, sends one LLM call
        per file to summarize all tests in it. Falls back to heuristic if no LLM.
        """
        query = """
        MATCH (s:TestSymbol)
        WHERE s.summary IS NULL
          AND (s.project_id = $project_id
               OR EXISTS { MATCH (p:Project {sql_id: $project_id})-[:CONTAINS]->(:TestFile)-[:DEFINES]->(s) })
        RETURN s.name as name, s.file_path as file_path
        """
        symbols = self.neo4j.query(query, {"project_id": project_id})
        
        if not symbols:
            return 0
        
        # Try Cloudflare LLM first
        try:
            from .providers.cloudflare import CloudflareProvider
            provider = CloudflareProvider()
        except Exception:
            provider = None
        
        # Fallback to heuristic if no LLM available
        if not provider:
            return self._heuristic_summarize_tests(project_id, symbols)

        from collections import defaultdict
        file_groups = defaultdict(list)
        for sym in symbols:
            file_groups[sym["file_path"]].append(sym["name"])
        
        import asyncio
        semaphore = asyncio.Semaphore(3)
        success = 0
        
        async def summarize_file(file_path: str, test_names: list) -> int:
            async with semaphore:
                try:
                    full_path = file_path if os.path.isabs(file_path) else os.path.join(repo_root or "", file_path)
                    if not os.path.exists(full_path):
                        logger.warning(f"File not found: {full_path}")
                        return 0
                    
                    with open(full_path, "r") as f:
                        content = f.read()
                    
                    test_list = "\n".join(f"- {t}" for t in test_names)
                    file_content = content[:3000]
                    prompt_text = (
                        f"Below is a test file. For each listed test function, provide a one-line (max 12 words) "
                        f"summary of what it tests.\n\n"
                        f"Test names:\n{test_list}\n\n"
                        f"File content:\n{file_content}\n\n"
                        f"Respond in JSON format with test names as keys and summaries as values."
                    )
                    
                    request = LLMRequest(
                        provider_name="Cloudflare",
                        model_name=self.model_name,
                        prompt=prompt_text,
                        max_tokens=4096,
                        temperature=0.1
                    )
                    response = await provider.complete(request)
                    raw = response.content.strip()
                    if raw.startswith("Error:"):
                        logger.warning(f"LLM error for {file_path}: {raw[:200]}")
                        return 0
                    
                    import json as json_mod
                    raw_clean = raw.strip()
                    if raw_clean.startswith("```"):
                        raw_clean = raw_clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                    try:
                        summaries = json_mod.loads(raw_clean)
                    except json_mod.JSONDecodeError:
                        logger.warning(f"Could not parse LLM JSON for {file_path}: {raw[:200]}")
                        return 0
                    
                    count = 0
                    for test_name, summary in summaries.items():
                        if summary:
                            self.neo4j.query("""
                                MATCH (s:TestSymbol {name: $name, file_path: $fp})
                                WHERE s.project_id = $pid
                                SET s.summary = $summary
                            """, {"pid": project_id, "fp": file_path, "name": test_name, "summary": str(summary).strip('"\'')})
                            count += 1
                    return count
                except Exception as e:
                    logger.warning(f"Failed to summarize tests in {file_path}: {e}")
                    return 0
        
        tasks = [summarize_file(fp, names) for fp, names in list(file_groups.items())[:200]]
        for coro in asyncio.as_completed(tasks):
            success += await coro

        logger.info(f"LLM test summarization: {success}/{len(symbols)} success")

        # Heuristic fallback for any remaining NULL-summary symbols
        remaining = self.neo4j.query("""
            MATCH (s:TestSymbol)
            WHERE s.summary IS NULL AND s.project_id = $pid
            RETURN s.name as name, s.file_path as file_path
        """, {"pid": project_id})
        if remaining:
            logger.info(f"Filling {len(remaining)} remaining test symbols with heuristic summaries")
            self._heuristic_summarize_tests(project_id, remaining)
            success += len(remaining)

        return success

    def _heuristic_summarize_tests(self, project_id: int, symbols: List[Dict]) -> int:
        """Generate summaries for test symbols WITHOUT using an LLM."""
        import re
        count = 0
        
        for sym in symbols:
            name = sym.get("name", "")
            file_path = sym.get("file_path", "")
            
            # Strip common test prefixes/suffixes
            patterns_to_strip = [
                r"^test[_]?",
                r"[_]?test$",
                r"^Test",
                r"\.spec$",
                r"\.test$",
                r"^it[_]?",
                r"^describe[_]?",
            ]
            
            base_name = name
            for pattern in patterns_to_strip:
                base_name = re.sub(pattern, "", base_name, flags=re.IGNORECASE)
            
            # Capitalize if needed
            if base_name and not base_name[0].isupper():
                try:
                    base_name = base_name[0].upper() + base_name[1:]
                except IndexError:
                    base_name = name.title()
            
            # Get context from file path
            file_context = ""
            if file_path:
                parts = file_path.split("/")
                if len(parts) >= 2:
                    file_context = parts[0]
            
            # Build summary
            if file_context:
                summary = f"Tests {file_context} for {base_name}" if base_name else f"Tests {file_context}"
            elif base_name:
                summary = f"Tests for {base_name}"
            else:
                summary = "Test case"
            
            # Update in Neo4j — use project_id property as fallback
            self.neo4j.query("""
                MATCH (s:TestSymbol {name: $name, file_path: $fp})
                WHERE s.project_id = $pid
                SET s.summary = $summary
            """, {"pid": project_id, "fp": file_path, "name": name, "summary": summary})
            count += 1
        
        return count
