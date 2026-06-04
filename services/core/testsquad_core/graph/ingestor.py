import os
import asyncio
import logging
from typing import List, Dict, Optional
from .client import Neo4jClient
from .resolvers.python import PythonResolver
from .resolvers.typescript import TypescriptResolver

logger = logging.getLogger(__name__)

class GraphIngestor:
    def __init__(self, neo4j: Neo4jClient, project_id: int):
        self.neo4j = neo4j
        self.project_id = project_id
        self.ignored_dirs = {
            ".git", "node_modules", "venv", ".venv", "__pycache__", ".pytest_cache", 
            "lib", "site-packages", "bin", "include", "share",
            "cypress", "playwright", "e2e", "dist", "build", "out", "docs", "public", "assets",
            "scripts", "tools", "benchmarks", "website", "coverage", ".next", ".cache", "logs"
        }
        self.max_file_size = 1024 * 1024  # 1MB
        self.max_symbols_per_file = 20    # Threshold for high-value symbols only
        
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
            r"(^|/)tests?/",      # tests/ directory
            r"(^|/)__tests__/",   # __tests__ directory
            r"(^|/)cypress/",     # cypress directory
            r"(^|/)playwright/",  # playwright directory
            r"(^|/)e2e/",         # e2e directory
            r"test_.*\.py$",      # test_*.py
            r".*_test\.py$",      # *_test.py
            r".*\.spec\.(ts|js|tsx|jsx)$", # *.spec.ts/js
            r".*\.test\.(ts|js|tsx|jsx)$", # *.test.ts/js
            r".*\.cy\.(ts|js)$"   # *.cy.ts/js (Cypress)
        ]
        import re
        return any(re.search(pattern, rel_path) for pattern in test_patterns)

    def discover_source_root(self, repo_root: str) -> str:
        """Heuristic to find the actual source root (e.g., src/, lib/, packages/)."""
        # Check common source directories
        for src_dir in ["src", "lib", "packages", "app", "source"]:
            src_path = os.path.join(repo_root, src_dir)
            if os.path.isdir(src_path):
                return src_path
        # If no common source dir, use repo root but check subdirs
        return repo_root

    async def ingest_repo_stream(self, repo_root: str):
        """Streaming version of ingest_repo for real-time progress updates."""
        self.neo4j.ensure_constraints()
        
        # Scan from repo root; ignored_dirs + extension filters handle the rest
        search_root = repo_root
        
        # 1. Purge existing file/symbol nodes for this project to ensure a clean slate
        yield {"event": "log", "data": "🧹 Purging existing project artifacts for a clean sync..."}
        self.neo4j.query("""
            MATCH (p:Project {sql_id: $pid})-[*1..2]->(n)
            WHERE n:File OR n:Symbol OR n:TestSymbol OR n:Document
            DETACH DELETE n
        """, {"pid": self.project_id})
        # Also drop orphaned File nodes (from previous failed runs) that are in the repo tree
        candidate_paths = []
        for root, dirs, files in os.walk(search_root):
            for f in files:
                if f.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
                    rel = os.path.relpath(os.path.join(root, f), repo_root)
                    candidate_paths.append(rel)
                    if len(candidate_paths) >= 500:
                        break
            if len(candidate_paths) >= 500:
                break
        if candidate_paths:
            self.neo4j.query("""
                MATCH (f:File)
                WHERE f.path IN $paths
                DETACH DELETE f
            """, {"paths": candidate_paths})

        files_to_sync = []
        docs_to_sync = []
        yield {"event": "reasoning", "data": f"Scanning tree at {search_root}..."}
        
        total_walked = 0
        for root, dirs, files in os.walk(search_root):
            total_walked += len(files)
            # Global path exclusion: If any part of the path is in ignored_dirs, skip it
            rel_root = os.path.relpath(root, repo_root)
            path_parts = [p for p in rel_root.split(os.sep) if p and p != "."]
            
            if any(p in self.ignored_dirs or p.startswith(".") for p in path_parts):
                dirs[:] = [] # Stop recursion
                continue

            for file in files:
                # Skip hidden files and template files
                if file.startswith(".") or file.endswith(".sample") or file.endswith(".tmpl"):
                    continue
                    
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, repo_root)
                yield {"event": "log", "data": f"DEBUG: Walked file: {rel_path}"}
                
                # Path Normalization: Standardize relative path to strip environment-specific prefixes (like /app/)
                # This ensures consistent node identifiers across different sync environments.
                normalized_rel_path = rel_path
                if normalized_rel_path.startswith("app/") or normalized_rel_path.startswith("./app/"):
                    normalized_rel_path = normalized_rel_path.replace("app/", "", 1).lstrip("./")
                elif normalized_rel_path.startswith("services/core/"):
                    normalized_rel_path = normalized_rel_path.replace("services/core/", "", 1)
                
                # Double check normalized_rel_path for ignored components
                if any(p in self.ignored_dirs or (p.startswith(".") and p != ".") for p in normalized_rel_path.split(os.sep)):
                    continue
                if self.is_test_file(normalized_rel_path):
                    yield {"event": "log", "data": f"DEBUG: Skipping test file: {normalized_rel_path}"}
                    continue
                    
                # Skip minified files by extension OR name pattern
                if ".min." in file or "-min." in file:
                    continue
                    
                if file.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
                    # Skip common build/config files in root
                    root_scripts = {"webpack.config.js", "vite.config.ts", "jest.config.js", "generate-sitemaps.js", "tailwind.config.js"}
                    if file in root_scripts:
                        continue
                        
                    yield {"event": "log", "data": f"DEBUG: Found candidate file: {normalized_rel_path}"}
                    f_full_path = os.path.join(root, file)
                    
                    # Size check
                    if os.path.getsize(f_full_path) > self.max_file_size:
                        continue
                        
                    # ⚠️ CRITICAL: Check for extremely long lines (indicative of minification)
                    try:
                        with open(f_full_path, "r", errors="ignore") as tf:
                            first_few_lines = [tf.readline() for _ in range(5)]
                            if any(len(line) > 1000 for line in first_few_lines):
                                logger.debug("Skipping likely minified file: %s", rel_path)
                                continue
                    except Exception:
                        pass
                        
                    language = "python" if file.endswith(".py") else "typescript"
                    if file.endswith((".js", ".jsx")):
                        language = "javascript"
                        
                    files_to_sync.append((f_full_path, normalized_rel_path, language))
                elif file.endswith((".md", ".txt", ".mdx")):
                    f_full_path = os.path.join(root, file)
                    if os.path.getsize(f_full_path) <= 5 * 1024 * 1024:
                        docs_to_sync.append((f_full_path, normalized_rel_path))
        
        yield {"event": "reasoning", "data": f"Walked {total_walked} files. Found {len(files_to_sync)} product files (TS/JS/PY) to index in {repo_root}..."}
        
        # 4. Phase 2: High-Precision LSP Resolution
        yield {"event": "reasoning", "data": "Starting High-Precision LSP servers for deep call resolution..."}
        
        # Detect primary language for LSP
        primary_lang = "python" if any(f[0].endswith(".py") for f in files_to_sync) else "typescript"
        lsp_cmd = ["pyright-langserver", "--stdio"] if primary_lang == "python" else ["typescript-language-server", "--stdio"]
        
        # For TypeScript LSP, ensure typescript is installed in workspace
        if primary_lang == "typescript":
            tsconfig_exists = os.path.exists(os.path.join(repo_root, "tsconfig.json"))
            node_modules_exists = os.path.exists(os.path.join(repo_root, "node_modules", "typescript"))
            if not node_modules_exists:
                yield {"event": "reasoning", "data": "Installing TypeScript for LSP resolution..."}
                install_process = await asyncio.create_subprocess_exec(
                    "npm", "install", "typescript", "--save-dev",
                    cwd=repo_root,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await install_process.communicate()
        
        # Log for debugging - remove after verifying LSP works
        logger.info(f"Detected primary language: {primary_lang}, LSP command: {lsp_cmd}")
        
        from .lsp_client import LspClient
        semaphore = asyncio.Semaphore(5)  # Limit concurrent file processing
        async with LspClient(lsp_cmd, repo_root) as lsp:
            indexed_count = 0
            
            async def process_single_file(file_info):
                nonlocal indexed_count
                f_path, rel_path, language = file_info
                async with semaphore:
                    try:
                        with open(f_path, "rb") as f:
                            content = f.read()
                        
                        # Get Resolver and extract symbols
                        resolver = self.resolvers.get(language)
                        if not resolver:
                            return
                        
                        # Fix: Call resolve_relationships, not extract_metadata
                        symbols, imports, calls = resolver.resolve_relationships(rel_path, content.decode("utf-8", errors="ignore"))
                        
                        # 3. Index to Neo4j
                        self.neo4j.index_file_symbols(self.project_id, rel_path, symbols, language)
                        
                        # 3. Index Imports (Precise + Heuristic)
                        async def resolve_one_import(imp):
                            target_path = None
                            # Try LSP first if coordinates are available
                            if "line" in imp:
                                definition = await lsp.get_definition(f_path, imp["line"], imp["character"])
                                if definition:
                                    loc = definition[0] if isinstance(definition, list) else definition
                                    target_uri = loc.get("uri", "")
                                    if target_uri:
                                        target_abs_path = target_uri.replace("file://", "")
                                        if os.path.exists(target_abs_path):
                                            target_path = os.path.relpath(target_abs_path, repo_root)
                            
                            # Fallback to heuristics
                            if not target_path:
                                target_path = self._resolve_import_to_path(imp["target"], repo_root)
                                
                            if target_path:
                                self.neo4j.add_relationship(
                                    from_node={"path": rel_path}, to_node={"path": target_path}, rel_type="IMPORTS"
                                )

                        if imports:
                            for imp in imports:
                                target_path = self._resolve_import_to_path(imp["target"], repo_root, language, rel_path)
                                if target_path:
                                    self.neo4j.add_file_import(self.project_id, rel_path, target_path)

                        # 4. Deep Resolution (LSP)
                        if calls:
                            for call in calls:
                                # Use LSP if available, otherwise fallback to name-based
                                definition = await lsp.get_definition(f_path, call["line"], call["character"])
                                if definition:
                                    loc = definition[0] if isinstance(definition, list) else definition
                                    target_uri = loc.get("uri", "")
                                    target_range = loc.get("range", {}).get("start", {})
                                    if target_uri and "line" in target_range:
                                        t_abs = target_uri.replace("file://", "")
                                        if os.path.exists(t_abs):
                                            t_rel = os.path.relpath(t_abs, repo_root)
                                            self.neo4j.add_precise_call(self.project_id, rel_path, call["caller"], t_rel, target_range["line"] + 1)
                                else:
                                    self._add_call_relationship(self.project_id, rel_path, call["caller"], call["callee"])
                        
                        indexed_count += 1
                    except Exception as e:
                        logger.error(f"Failed to process {rel_path}: {e}")

            # Execute parallel processing
            sync_tasks = [process_single_file(f) for f in files_to_sync]
            
            # Add timeout to prevent infinite hang
            total_files = len(files_to_sync)
            logger.info(f"Starting parallel processing of {total_files} files with {asyncio.Semaphore(5)._value} concurrent workers")
            
            # Use as_completed to provide streaming feedback
            for coro in asyncio.as_completed(sync_tasks):
                try:
                    await asyncio.wait_for(coro, timeout=30.0)  # 30s timeout per file
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout processing file, continuing...")
                except Exception as e:
                    logger.error(f"Error in file processing: {e}")
                
                if indexed_count % 10 == 0 or indexed_count == total_files:
                    yield {"event": "reasoning", "data": f"Indexed {indexed_count}/{total_files} files (Production Brain)..."}

            yield {"event": "reasoning", "data": f"Success: Ingested {indexed_count} functional paths into the Graph."}
        
        yield {"event": "log", "data": "Finalizing graph relationships..."}
        
        # 5. Phase 3: Multimodal Documentation Indexing
        if docs_to_sync:
            yield {"event": "log", "data": f"📚 Indexing {len(docs_to_sync)} Multimodal Documentation files..."}
            try:
                # Fetch all known symbols for quick mention matching
                all_symbols = self.neo4j.get_all_symbols(self.project_id)
                # Optimize by using symbols > 4 chars to reduce false positives
                symbol_names = {s["name"]: s["file_path"] for s in all_symbols if len(s["name"]) > 4}
                
                def extract_mentions(text):
                    mentions = []
                    for sym_name, sym_file in symbol_names.items():
                        # Simple boundary check for the symbol in the text
                        if f" {sym_name} " in text or f" {sym_name}(" in text or f" {sym_name}." in text or f"`{sym_name}`" in text or f"#{sym_name}" in text:
                            mentions.append((sym_name, sym_file))
                    return mentions

                docs_indexed = 0
                for f_path, rel_path in docs_to_sync:
                    try:
                        with open(f_path, "r", errors="ignore") as f:
                            content = f.read()
                        
                        if len(content) > 50000:
                            content = content[:50000]

                        self.neo4j.index_document(self.project_id, rel_path, content)
                        
                        mentions = extract_mentions(content)
                        for sym_name, sym_file in mentions:
                            self.neo4j.add_document_mention(rel_path, sym_name, sym_file)
                            
                        docs_indexed += 1
                    except Exception as e:
                        logger.error(f"Failed to process document {rel_path}: {e}")
                
                yield {"event": "log", "data": f"✅ Multimodal indexing complete. Linked symbols in {docs_indexed} documents."}
            except Exception as e:
                logger.error(f"Multimodal indexing failed: {e}")
                yield {"event": "log", "data": f"⚠️ Document indexing skipped: {e}"}
        
        try:
            yield {"event": "log", "data": "🏙️ Building Conceptual Neighborhoods (Community Detection)..."}
            from ..analysis.community import CommunityDetector
            detector = CommunityDetector(self.neo4j)
            detector.run_and_save()
        except Exception as e:
            logger.error(f"Community detection failed: {e}")
            yield {"event": "log", "data": f"⚠️ Community detection incomplete: {e}"}

    def _resolve_import_to_path(self, module_str: str, repo_root: str, language: str, from_path: str) -> Optional[str]:
        if language == "python":
            parts = module_str.split(".")
            potentials = [os.path.join(*parts) + ".py", os.path.join(*parts, "__init__.py")]
        else: # ts/js
            if module_str.startswith("."):
                # Resolve relative to from_path
                base_dir = os.path.dirname(os.path.join(repo_root, from_path))
                potentials = [os.path.normpath(os.path.join(base_dir, module_str + ext)) for ext in [".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx"]]
                # Convert back to relative to repo_root
                potentials = [os.path.relpath(p, repo_root) for p in potentials]
            else:
                potentials = [module_str + ext for ext in [".ts", ".tsx", ".js", ".jsx"]]
        
        for p in potentials:
            if os.path.exists(os.path.join(repo_root, p)): return p
        return None

    def _add_call_relationship(self, project_id: int, from_file: str, from_symbol: str, callee_name: str):
        query = """
        MATCH (p:Project {sql_id: toInteger($pid)})
        MATCH (p)-[:CONTAINS]->(:File)-[:DEFINES]->(s1 {name: $from_name, file_path: $from_file})
        MATCH (p)-[:CONTAINS]->(:File)-[:DEFINES]->(s2 {name: $to_name})
        WHERE s1 <> s2
        MERGE (s1)-[:CALLS]->(s2)
        """
        self.neo4j.query(query, {"pid": project_id, "from_name": from_symbol, "from_file": from_file, "to_name": callee_name})
