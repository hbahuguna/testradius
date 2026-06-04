import os
import asyncio
import logging
from typing import List, Dict, Optional, Tuple
from .client import Neo4jClient
from .resolvers.python import PythonResolver
from .resolvers.typescript import TypescriptResolver

logger = logging.getLogger(__name__)


class TestGraphIngestor:
    def __init__(self, neo4j: Neo4jClient, project_id: int):
        self.neo4j = neo4j
        self.project_id = project_id
        self.ignored_dirs = {
            ".git", "node_modules", "venv", ".venv", "__pycache__", ".pytest_cache",
            "lib", "site-packages", "bin", "include", "share", "dist", "build", "out"
        }
        self.max_file_size = 1024 * 1024  # 1MB

        from .resolvers.python import PythonResolver
        from .resolvers.typescript import TypescriptResolver
        self.resolvers = {
            "python": PythonResolver(),
            "typescript": TypescriptResolver(use_typescript=True),
            "javascript": TypescriptResolver(use_typescript=False)
        }

    def is_test_file(self, rel_path: str) -> bool:
        """Heuristic to identify if a file is a test file."""
        test_patterns = [
            r"(^|/)tests?/",
            r"(^|/)__tests__/",
            r"(^|/)cypress/",
            r"(^|/)playwright/",
            r"(^|/)e2e/",
            r"test_.*\.py$",
            r".*_test\.py$",
            r".*\.spec\.(ts|js|tsx|jsx)$",
            r".*\.test\.(ts|js|tsx|jsx)$",
            r".*\.cy\.(ts|js)$"
        ]
        import re
        return any(re.search(pattern, rel_path) for pattern in test_patterns)

    async def ingest_test_repo_stream(self, repo_root: str):
        """Streaming version of test repo ingestion with AST + LSP + Community Detection."""
        self.neo4j.ensure_constraints()

        yield {"event": "reasoning", "data": "🧪 Starting Test Brain Sync (AST + LSP + Leiden)..."}

        # 1. Purge existing test nodes
        yield {"event": "log", "data": "🧹 Purging existing test artifacts..."}
        self.neo4j.query("""
            MATCH (p:Project {sql_id: $pid})-[*1..2]->(n)
            WHERE n:TestFile OR n:TestSymbol
            DETACH DELETE n
        """, {"pid": self.project_id})

        # 2. Discover test files
        files_to_sync = []
        yield {"event": "reasoning", "data": "Scanning test files..."}

        for root, dirs, files in os.walk(repo_root):
            rel_root = os.path.relpath(root, repo_root)
            path_parts = [p for p in rel_root.split(os.sep) if p and p != "."]

            if any(p in self.ignored_dirs or p.startswith(".") for p in path_parts):
                dirs[:] = []
                continue

            for file in files:
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, repo_root)

                normalized_rel_path = rel_path
                if normalized_rel_path.startswith("app/") or normalized_rel_path.startswith("./app/"):
                    normalized_rel_path = normalized_rel_path.replace("app/", "", 1).lstrip("./")

                if not self.is_test_file(normalized_rel_path):
                    continue

                if file.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
                    try:
                        if os.path.getsize(abs_path) > self.max_file_size:
                            continue
                    except:
                        continue

                    language = "python" if file.endswith(".py") else "typescript"
                    if file.endswith((".js", ".jsx")):
                        language = "javascript"

                    files_to_sync.append((abs_path, normalized_rel_path, language))

        yield {"event": "reasoning", "data": f"Found {len(files_to_sync)} test files to index..."}

        # 3. AST-based symbol extraction + LSP resolution
        primary_lang = "python" if any(f[0].endswith(".py") for f in files_to_sync) else "typescript"
        lsp_cmd = ["pyright-langserver", "--stdio"] if primary_lang == "python" else ["typescript-language-server", "--stdio"]

        from .lsp_client import LspClient
        semaphore = asyncio.Semaphore(5)
        indexed_count = 0

        async with LspClient(lsp_cmd, repo_root) as lsp:
            async def process_test_file(file_info):
                nonlocal indexed_count
                f_path, rel_path, language = file_info
                async with semaphore:
                    try:
                        with open(f_path, "rb") as f:
                            content = f.read()

                        resolver = self.resolvers.get(language)
                        if not resolver:
                            return

                        symbols, imports, calls = resolver.resolve_relationships(rel_path, content.decode("utf-8", errors="ignore"))

                        # Index test symbols to Neo4j
                        test_type = self._infer_test_type(rel_path, content.decode("utf-8", errors="ignore"))
                        self.neo4j.index_test_file_symbols(self.project_id, rel_path, symbols, language, test_type)

                        # Index imports (heuristic + LSP)
                        for imp in imports:
                            target_path = self._resolve_import_to_path(imp["target"], repo_root, language, rel_path)
                            if target_path:
                                self.neo4j.add_test_import(self.project_id, rel_path, target_path)

                        # Index test calls via LSP
                        for call in calls:
                            definition = await lsp.get_definition(f_path, call["line"], call["character"])
                            if definition:
                                loc = definition[0] if isinstance(definition, list) else definition
                                target_uri = loc.get("uri", "")
                                if target_uri:
                                    target_abs = target_uri.replace("file://", "")
                                    if os.path.exists(target_abs):
                                        target_rel = os.path.relpath(target_abs, repo_root)
                                        target_range = loc.get("range", {}).get("start", {})
                                        if "line" in target_range:
                                            self.neo4j.add_test_call(self.project_id, rel_path, call["caller"], target_rel, target_range["line"] + 1)

                        indexed_count += 1
                    except Exception as e:
                        logger.error(f"Failed to process {rel_path}: {e}")

            sync_tasks = [process_test_file(f) for f in files_to_sync]
            for coro in asyncio.as_completed(sync_tasks):
                await coro
                if indexed_count % 10 == 0 or indexed_count == len(files_to_sync):
                    yield {"event": "reasoning", "data": f"Indexed {indexed_count}/{len(files_to_sync)} test files..."}

        yield {"event": "reasoning", "data": f"Success: Ingested {indexed_count} test files into Graph."}

        # 5. Generate semantic summaries for test symbols (needed for vector matching)
        try:
            yield {"event": "log", "data": "📝 Generating test symbol summaries..."}
            from ..intelligence.summarizer import SymbolSummarizer
            summarizer = SymbolSummarizer(self.neo4j)
            summary_count = summarizer.summarize_symbols_for_tests(self.project_id)
            yield {"event": "log", "data": f"✅ Generated {summary_count} test summaries."}
        except Exception as e:
            logger.error(f"Test summarization failed: {e}")
            yield {"event": "log", "data": f"⚠️ Test summarization skipped: {e}"}

        # 6. Test Community Detection (Leiden)
        try:
            yield {"event": "log", "data": "🏠 Building Test Communities (Leiden Detection)..."}
            from ..analysis.community import TestCommunityDetector
            detector = TestCommunityDetector(self.neo4j)
            detector.run_and_save()
            yield {"event": "log", "data": "✅ Test community detection complete."}
        except Exception as e:
            logger.error(f"Test community detection failed: {e}")
            yield {"event": "log", "data": f"⚠️ Test community detection incomplete: {e}"}

    def _infer_test_type(self, file_path: str, content: str) -> str:
        """Infer the type of test (unit, e2e, integration)."""
        content_lower = content.lower()
        path_lower = file_path.lower()

        if "/e2e/" in path_lower or "/playwright/" in path_lower or "playwright" in content_lower:
            return "e2e"
        elif "/integration/" in path_lower or "integration" in content_lower:
            return "integration"
        elif "/cypress/" in path_lower or "cypress" in content_lower:
            return "e2e"
        else:
            return "unit"

    def _resolve_import_to_path(self, module_str: str, repo_root: str, language: str, from_path: str) -> Optional[str]:
        """Resolve import statement to file path."""
        if language == "python":
            parts = module_str.split(".")
            potentials = [os.path.join(*parts) + ".py", os.path.join(*parts, "__init__.py")]
        else:
            if module_str.startswith("."):
                base_dir = os.path.dirname(os.path.join(repo_root, from_path))
                potentials = [os.path.normpath(os.path.join(base_dir, module_str + ext)) for ext in [".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx"]]
                potentials = [os.path.relpath(p, repo_root) for p in potentials]
            else:
                potentials = [module_str + ext for ext in [".ts", ".tsx", ".js", ".jsx"]]

        for p in potentials:
            if os.path.exists(os.path.join(repo_root, p)):
                return p
        return None