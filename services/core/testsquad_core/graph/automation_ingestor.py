import os
import re
import asyncio
import logging
import base64
import functools
from github import Github, Auth
from .client import Neo4jClient

logger = logging.getLogger(__name__)

class AutomationIngestor:
    def __init__(self, neo4j: Neo4jClient, project_id: int):
        self.neo4j = neo4j
        self.project_id = project_id
        
        # Regex to capture test names from TS/JS/Playwright/Jest and Python/Pytest
        self.js_ts_pattern = re.compile(r"^\s*(?:test|test\.describe|it|describe)\s*\(\s*['\"](.*?)['\"]", re.MULTILINE)
        self.py_pattern = re.compile(r"^\s*(?:async\s+)?def\s+(test_[a-zA-Z0-9_]*)\s*\(", re.MULTILINE)

    async def ingest_repo_stream(self, repo_full_name: str, github_token: str):
        """Fetches the automation repo via PyGithub, parses AST, yields SSE events, and ingests Neo4j."""
        yield {"event": "reasoning", "data": f"Connecting to Github API to fetch `{repo_full_name}`..."}
        
        try:
            g = Github(auth=Auth.Token(github_token))
            repo = g.get_repo(repo_full_name)
            
            yield {"event": "reasoning", "data": f"Fetching repository file tree for branch `{repo.default_branch}`..."}
            tree = repo.get_git_tree(repo.default_branch, recursive=True)
            
            test_files = [t for t in tree.tree if t.type == "blob" and (
                t.path.endswith((".spec.ts", ".test.ts", ".spec.js", ".test.js", ".cy.ts", ".cy.js", "_test.py")) or 
                "test_" in t.path or "/tests/" in t.path or "/__tests__/" in t.path or "/e2e/" in t.path
            )]
            
            yield {"event": "reasoning", "data": f"Found {len(test_files)} potential automation test files across the repository. Filtering for E2E-specific routines..."}
            
            # Clear existing automation nodes for this project ID
            self.neo4j.query("""
                MATCH (p:Project {sql_id: $pid})-[:CONTAINS]->(tf:TestFile)
                OPTIONAL MATCH (tf)-[:DEFINES]->(ts:TestSymbol) 
                DETACH DELETE ts, tf
            """, {"pid": self.project_id})

            # Process files concurrently with Semaphore
            semaphore = asyncio.Semaphore(10)
            count = 0
            processed_files =0

            async def process_single_test_file(f):
                nonlocal count, processed_files
                async with semaphore:
                    try:
                        # Use run_in_executor for synchronous PyGithub call
                        loop = asyncio.get_event_loop()
                        content_obj = await loop.run_in_executor(None, repo.get_contents, f.path)
                        decoded_content = base64.b64decode(content_obj.content).decode("utf-8", errors="ignore")
                        
                        is_e2e = any(keyword in decoded_content.lower() for keyword in ["playwright", "cypress", "@playwright/test", "cy.", "page"]) or "/e2e/" in f.path.lower()
                        is_unit = f.path.endswith((".test.ts", ".spec.ts", ".test.js", ".spec.js"))
                        
                        if not (is_e2e or is_unit):
                            return 0

                        lang = "typescript" if f.path.endswith((".ts", ".js")) else "python"
                        pattern = self.js_ts_pattern if lang == "typescript" else self.py_pattern
                        
                        # Process and index synchronously but in executor
                        c = await loop.run_in_executor(None, functools.partial(self._process_content, f.path, decoded_content, pattern, lang))
                        return c
                    except Exception as e:
                        logger.warning(f"Failed to parse file {f.path}: {e}")
                        return 0

            tasks = [process_single_test_file(f) for f in test_files]
            for coro in asyncio.as_completed(tasks):
                c = await coro
                count += c
                processed_files += 1
                if processed_files % 10 == 0 or processed_files == len(test_files):
                    yield {"event": "reasoning", "data": f"Scanned {processed_files}/{len(test_files)} files (Test Brain)..."}
                    
            yield {"event": "status", "data": {"status": "INGEST_COMPLETED", "message": f"Successfully ingested {count} E2E TestSymbols into the Graph Database."}}
            
            # Generate test summaries for vector matching
            try:
                yield {"event": "log", "data": "📝 Generating test symbol summaries..."}
                from testsquad_core.intelligence.summarizer import SymbolSummarizer
                summarizer = SymbolSummarizer(self.neo4j)
                summary_count = await summarizer.summarize_symbols_for_tests(self.project_id)
                yield {"event": "log", "data": f"✅ Generated {summary_count} test summaries."}
            except Exception as se:
                logger.warning(f"Test summarization failed: {se}")
                yield {"event": "log", "data": f"⚠️ Test summarization skipped: {se}"}
            
        except Exception as e:
            logger.error(f"Automation ingestion crashed: {str(e)}")
            yield {"event": "error", "data": f"Critical Failure: {str(e)}"}
            yield {"event": "status", "data": {"status": "FAILED"}}

    def _process_content(self, rel_path: str, content: str, pattern: re.Pattern, language: str) -> int:
        self.neo4j.index_test_file(self.project_id, rel_path, language)
        
        tests_found = 0
        for match in pattern.finditer(content):
            test_name = match.group(1)
            start_line = content.count('\n', 0, match.start()) + 1
            
            self.neo4j.index_test_symbol(
                file_path=rel_path,
                name=test_name,
                sym_type="test",
                start_line=start_line,
                end_line=start_line + 5,
                test_type="e2e" if "playwright" in content.lower() else "unit"
            )
            tests_found += 1
        return tests_found
