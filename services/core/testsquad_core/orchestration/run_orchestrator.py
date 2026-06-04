import os
import re
import json
import time
import asyncio
import logging
from uuid import UUID
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from testsquad_shared.api import ExecutionRequest, TaskStatus
from testsquad_shared.intelligence.prompt_registry import prompt_registry
from testsquad_shared.models import LLMRequest
from testsquad_core.graph.client import Neo4jClient
from testsquad_core.clients.executor import ExecutorClient
from testsquad_core.persistence.run_models import Run, RunResult
from testsquad_shared.persistence.models import StyleCapsule, Project
from testsquad_core.intelligence.registry import llm_registry, initialize_standard_providers
from testsquad_core.intelligence.providers.base import BaseProvider

logger = logging.getLogger(__name__)

class RunOrchestrator:
    """Manages the lifecycle of an immutable test run."""

    def __init__(self, neo4j: Neo4jClient, executor: ExecutorClient, session: AsyncSession, llm_client: Optional[BaseProvider] = None):
        self.neo4j = neo4j
        self.executor = executor
        self.session = session
        self.llm_client = llm_client
        
        # Ensure LLM providers are ready
        if not self.llm_client:
            initialize_standard_providers()

    async def stream_full_cycle(self, project_id: int, commit_sha: str, max_symbols: int = 5, llm_model: Optional[str] = None, llm_provider: str = "Google", file_paths: Optional[List[str]] = None, automation_repo: Optional[str] = None):
        """Orchestrates selection, generation, and execution, yielding events for streaming."""
        # Use strip() to handle empty strings from UI
        is_structural_only = not llm_model or not str(llm_model).strip()
        yield {"event": "log", "data": f"DEBUG: Orchestrator Mode - llm_model='{llm_model}', is_structural_only={is_structural_only}"}
        yield {"event": "reasoning", "data": f"Initializing {'Structural' if is_structural_only else 'Immortal'} Run for project {project_id} (SHA: {commit_sha[:7]})..."}
        
        # 1. Create Run record (Fetch it if already exists, but here it's usually passed)
        run_record = await self.session.execute(select(Run).where(Run.project_id == project_id, Run.commit_sha == commit_sha).order_by(Run.created_at.desc()))
        run = run_record.scalars().first()

        if automation_repo:
            yield {"event": "reasoning", "data": "Scanning automation repo for existing tests mapping...\n*Mapping complete. Existing tests will be triggered via CI.*"}

        if run:
            run.status = TaskStatus.RUNNING
            # Avoid committing here to let the main loop manage session state
            yield {"event": "status", "data": {"run_id": run.id, "status": "RUNNING"}}

        try:
            # 2. Select top symbols by PRI
            if file_paths:
                yield {"event": "reasoning", "data": f"Identifying high-risk changes within {len(file_paths)} modified files..."}
            else:
                yield {"event": "reasoning", "data": "Querying Knowledge Graph for project-wide high-risk symbols..."}
                
            symbols = await self._select_risky_symbols(project_id, max_symbols, file_paths)
            
            if not symbols and file_paths:
                yield {"event": "reasoning", "data": "No indexed symbols found in modified files. Falling back to project-wide risk analysis."}
                symbols = await self._select_risky_symbols(project_id, max_symbols)
            
            if not symbols:
                yield {"event": "reasoning", "data": "⚠️ No high-priority symbols found in the Knowledge Graph. If this is a new project, please ensure you have clicked **'Sync Project Brain'** in the sidebar to index the codebase."}
            
            if symbols:
                yield {"event": "reasoning", "data": f"Selected {len(symbols)} impacted symbols for analysis."}

            generated_files = []
            for sym in symbols:
                try:
                    async for event in self._process_symbol_stream(project_id, run.id, sym, commit_sha, llm_model, llm_provider, automation_repo, generated_files, is_structural_only):
                        yield event
                except Exception as e:
                    logger.error(f"Failed to process symbol {sym['name']}: {e}")
                    yield {"event": "log", "data": f"Error processing {sym['name']}: {str(e)}"}

            if automation_repo and generated_files:
                yield {"event": "reasoning", "data": f"Creating consolidated Pull Request in `{automation_repo}` for {len(generated_files)} files..."}
                try:
                    from github import Github, Auth
                    run_res = await self.session.execute(select(Run).where(Run.id == run.id))
                    fresh_run = run_res.scalar_one_or_none()
                    github_token = fresh_run.run_metadata.get("github_token") if fresh_run and fresh_run.run_metadata else os.getenv("GITHUB_TOKEN")
                    
                    if github_token:
                        g = Github(auth=Auth.Token(github_token))
                        auto_repo_obj = g.get_repo(automation_repo)
                        
                        main_ref = auto_repo_obj.get_git_ref(f"heads/{auto_repo_obj.default_branch}")
                        branch_name = f"testsquad/run-{run.id}-{int(time.time())}"
                        
                        auto_repo_obj.create_git_ref(ref=f"refs/heads/{branch_name}", sha=main_ref.object.sha)
                        repo_name = fresh_run.run_metadata.get("full_name", "the source repository") if fresh_run and fresh_run.run_metadata else "the source repo"
                        
                        for gf in generated_files:
                            commit_msg = f"test: auto-generated test for {gf['symbol_name']}\n\nGenerated by TestSquad based on changes in {repo_name} at commit {commit_sha}."
                            auto_repo_obj.create_file(
                                path=gf['file_path'],
                                message=commit_msg,
                                content=gf['content'],
                                branch=branch_name
                            )
                            
                            result = RunResult(
                                run_id=run.id,
                                symbol_name=gf["symbol_name"],
                                file_path=gf["symbol_file_path"],
                                status=TaskStatus.COMPLETED,
                                test_code=gf['content'],
                                exit_code=0,
                                log_stream=f"PR Created",
                                error_message=None
                            )
                            self.session.add(result)
                            
                        pr = auto_repo_obj.create_pull(
                            title=f"TestSquad: Automated Test Suite for `{repo_name}` Run {run.id}",
                            body=f"This PR was automatically generated by TestSquad after detecting high-risk changes in `{repo_name}`.\n\n### Generated Tests\n" + "\n".join([f"- **{gf['symbol_name']}**: `{gf['file_path']}`" for gf in generated_files]),
                            head=branch_name,
                            base=auto_repo_obj.default_branch
                        )
                        
                        for r in self.session.new:
                            if isinstance(r, RunResult) and r.run_id == run.id:
                                r.log_stream = f"PR Created: {pr.html_url}"
                                
                        await self.session.commit()
                        yield {"event": "reasoning", "data": f"✅ Successfully created unified PR: [#{pr.number}]({pr.html_url})"}
                except Exception as e:
                    logger.error(f"Failed to create unified PR: {e}")
                    yield {"event": "error", "data": f"Failed to create consolidated PR in `{automation_repo}`: {e}"}

            yield {"event": "reasoning", "data": "Analysis cycle complete."}
            yield {"event": "status", "data": {"run_id": run.id if run else None, "status": "COMPLETED"}}
            
        except Exception as e:
            logger.error(f"Run orchestration failed: {e}")
            if run:
                run.status = TaskStatus.FAILED
                run.updated_at = datetime.utcnow()
                await self.session.commit()
            yield {"event": "reasoning", "data": f"Critical Failure: {str(e)}"}
            yield {"event": "status", "data": {"run_id": run.id if run else None, "status": "FAILED"}}

    async def _scan_for_existing_tests(self, project_id: int, changed_files: List[str], automation_repo: str) -> List[Dict]:
        """
        Scans for existing tests in the graph that are linked to the changed files,
        including those linked via neighborhood propagation.
        """
        query = """
        MATCH (p:Project {sql_id: toInteger($pid)})
        MATCH (p)-[:CONTAINS]->(f:File)-[:DEFINES]->(s:Symbol)
        WHERE f.path IN $changed_files
        OPTIONAL MATCH (ts:TestSymbol)-[:EVIDENCE]->(s)
        WITH s, COLLECT(DISTINCT ts) as all_tests
        UNWIND all_tests as ts
        WITH ts WHERE ts IS NOT NULL
        RETURN DISTINCT ts.name as name, ts.file_path as path

        UNION

        MATCH (p2:Project {sql_id: toInteger($pid)})
        MATCH (s2:Symbol {project_id: toInteger($pid)})
        WHERE s2.file_path IN $changed_files
        OPTIONAL MATCH (ts2:TestSymbol)-[:EVIDENCE]->(s2)
        WITH s2, COLLECT(DISTINCT ts2) as all_tests2
        UNWIND all_tests2 as ts
        WITH ts WHERE ts IS NOT NULL
        RETURN DISTINCT ts.name as name, ts.file_path as path
        """
        results = self.neo4j.query(query, {"pid": project_id, "changed_files": changed_files})
        return results

    async def _select_risky_symbols(self, project_id: int, limit: int, file_paths: Optional[List[str]] = None) -> List[Dict]:
        """Select top-N risky symbols, deduped by (name, file_path).

        Runs two independent Cypher queries (ingestor path and store_mappings
        path) instead of a UNION, because Neo4j UNION corrupts ORDER BY + LIMIT
        when computed column types differ between branches. Merging in Python
        gives correct ordering and dedup.
        """
        if file_paths:
            path_filter = "f.path IN $file_paths"
            sm_path_filter = "s2.file_path IN $file_paths"
        else:
            path_filter = "s.priority_risk_index IS NOT NULL"
            sm_path_filter = "s2.priority_risk_index IS NOT NULL OR s2.project_id IS NOT NULL"

        ingestor_query = f"""
            MATCH (p:Project {{sql_id: $project_id}})-[:CONTAINS]->(f:File)-[:DEFINES]->(s:Symbol)
            WHERE {path_filter}
            OPTIONAL MATCH (s)-[r:APPROVED_TEST]->(:TestSymbol)
            WITH s, f, COALESCE(s.priority_risk_index, 0) as raw_pri, 
                 COUNT(r) as approved_count
            OPTIONAL MATCH (ts_tests:TestSymbol)-[r2:EVIDENCE]->(s)
            WITH s, f, raw_pri, approved_count, COUNT(r2) as tests_count
            RETURN s.name as name, f.path as file_path,
                   raw_pri + CASE WHEN approved_count + tests_count > 0 THEN 5000.0 ELSE 0.0 END as pri,
                   CASE WHEN s.summary IS NULL THEN 'No summary available' ELSE s.summary END as summary, 
                   s.type as type, s.start_line as start, s.end_line as end
            ORDER BY pri DESC
        """
        store_mappings_query = f"""
            MATCH (p2:Project {{sql_id: $project_id}})
            MATCH (s2:Symbol {{project_id: $project_id}})
            WHERE {sm_path_filter}
            OPTIONAL MATCH (s2)-[r3:APPROVED_TEST]->(:TestSymbol)
            WITH s2, COALESCE(s2.priority_risk_index, 0) as raw_pri,
                 COUNT(r3) as approved_count
            OPTIONAL MATCH (ts_tests2:TestSymbol)-[r4:EVIDENCE]->(s2)
            WITH s2, raw_pri, approved_count, COUNT(r4) as tests_count
            RETURN s2.name as name, s2.file_path as file_path,
                   raw_pri + CASE WHEN approved_count + tests_count > 0 THEN 5000.0 ELSE 0.0 END as pri,
                   CASE WHEN s2.summary IS NULL THEN 'No summary available' ELSE s2.summary END as summary, 
                   s2.type as type, s2.start_line as start, s2.end_line as end
            ORDER BY pri DESC
        """

        params = {"project_id": project_id, "file_paths": file_paths or []}
        ingestor_results = self.neo4j.query(ingestor_query, params)
        sm_results = self.neo4j.query(store_mappings_query, params)

        # Merge, dedup by (name, file_path), sort by pri desc, limit
        combined = ingestor_results + sm_results
        combined.sort(key=lambda r: -r["pri"])

        seen = set()
        deduped = []
        for row in combined:
            key = (row["name"], row["file_path"])
            if key not in seen:
                seen.add(key)
                deduped.append(row)
                if len(deduped) >= limit:
                    break
        return deduped

    async def _process_symbol_stream(self, project_id: int, run_id: int, symbol: Dict, commit_sha: str, llm_model: Optional[str] = None, llm_provider: str = "Google", automation_repo: Optional[str] = None, generated_files: Optional[List[Dict]] = None, is_structural_only: bool = False):
        yield {"event": "reasoning", "data": f"--- Analyzing symbol: **{symbol['name']}** in `{symbol['file_path']}` ---"}
        
        # 0. Check for Existing Mappings
        approved_tests = self.neo4j.query("""
            MATCH (s:Symbol {name: $name, file_path: $path})
            OPTIONAL MATCH (ts:TestSymbol)-[:EVIDENCE]->(s)
            WITH COLLECT(DISTINCT ts) as all_tss
            UNWIND all_tss as ts
            WITH ts WHERE ts IS NOT NULL
            RETURN DISTINCT ts.name as test_name, ts.file_path as test_file
        """, {"name": symbol["name"], "path": symbol["file_path"]})
        
        if approved_tests:
            test_names = ", ".join([f"`{t['test_name']}`" for t in approved_tests])
            yield {"event": "reasoning", "data": f"✓ Reusing {len(approved_tests)} existing test(s): {test_names}"}
            
            result = RunResult(
                run_id=run_id,
                symbol_name=symbol["name"],
                file_path=symbol["file_path"],
                status=TaskStatus.COMPLETED,
                test_code=f"# Re-using existing tests:\n" + "\n".join([f"# - {t['test_file']} : {t['test_name']}" for t in approved_tests]),
                exit_code=0,
                log_stream="Delegated to CI/CD pipeline",
                error_message=None
            )
            self.session.add(result)
            await self.session.commit()
            return
            
        # 1. Gather Context (Dependencies)
        yield {"event": "reasoning", "data": f"Fetching structural dependencies for `{symbol['name']}` from Neo4j..."}
        dependencies = self.neo4j.query("""
            MATCH (s:Symbol {name: $name, file_path: $path})-[:CALLS]->(dep:Symbol)
            RETURN dep.name as name, dep.type as type, 
                   CASE WHEN dep.summary IS NULL THEN 'No summary available' ELSE dep.summary END as summary
            LIMIT 5
        """, {"name": symbol["name"], "path": symbol["file_path"]})
        yield {"event": "reasoning", "data": f"Found {len(dependencies)} dependency symbols."}

        # 1.5 Fetch Style Capsule
        capsule_result = await self.session.execute(
            select(StyleCapsule).where(StyleCapsule.project_id == project_id)
        )
        capsule = capsule_result.scalar_one_or_none()

        # 2. Fetch Repo Context if external
        repo_tree = None
        github_token = None
        if automation_repo:
            try:
                run_res = await self.session.execute(select(Run).where(Run.id == run_id))
                run = run_res.scalar_one_or_none()
                github_token = run.run_metadata.get("github_token") if run and run.run_metadata else os.getenv("GITHUB_TOKEN")
                
                if github_token:
                    from github import Github, Auth
                    g = Github(auth=Auth.Token(github_token))
                    auto_repo = g.get_repo(automation_repo)
                    
                    try:
                        tree = auto_repo.get_git_tree(auto_repo.default_branch, recursive=True)
                        test_files = [t.path for t in tree.tree if "test" in t.path.lower() or "e2e" in t.path.lower() or "spec" in t.path.lower()]
                        if test_files:
                            repo_tree = "\n".join(test_files[:40])
                            yield {"event": "reasoning", "data": f"Fetched existing test paths from `{automation_repo}` for context."}
                    except Exception as e:
                        logger.warning(f"Could not fetch tree for {automation_repo}: {e}")
            except Exception as e:
                logger.warning(f"Failed to setup Github context for {automation_repo}: {e}")

        # 3. Get Source Code
        code = self._get_code_snippet(symbol["file_path"], symbol["start"], symbol["end"])
        
        # 5. Targeted Test Generation
        if is_structural_only:
            yield {"event": "log", "data": "⏭️ Skipping AI test generation (Structural Mode active)."}
            return

        yield {"event": "reasoning", "data": f"Invoking LLM to generate tests for `{symbol['name']}`..."}
        prompt_data = prompt_registry.get_prompt(
            "generate_tests", 
            target_symbol=symbol, 
            dependencies=dependencies, 
            target_code=code,
            style_capsule=capsule.model_dump() if capsule else None,
            automation_repo=automation_repo,
            repo_tree=repo_tree
        )
        
        llm_client = self.llm_client or llm_registry.get_client(llm_provider)
        model_to_use = llm_model or prompt_data["metadata"].get("model", "gemini-1.5-flash-latest")
        
        response = await llm_client.complete(LLMRequest(
            provider_name=llm_provider, 
            model_name=model_to_use,
            prompt=prompt_data["content"],
            max_tokens=prompt_data["metadata"].get("max_tokens", 4096),
            temperature=prompt_data["metadata"].get("temperature", 0.1)
        ))
        
        extracted = self._extract_json_block(response.content)
        generated_test = extracted.get("code", "# Error extracting code")
        file_path = extracted.get("file_path", f"test_{symbol['name']}.py")
        
        yield {"event": "reasoning", "data": f"Test generation complete for `{symbol['name']}`\nTarget path: `{file_path}`"}
        
        if automation_repo and github_token and generated_files is not None:
            yield {"event": "reasoning", "data": f"Queued `{symbol['name']}` test for consolidated Pull Request..."}
            generated_files.append({
                "symbol_name": symbol["name"],
                "symbol_file_path": symbol["file_path"],
                "file_path": file_path,
                "content": generated_test
            })
            return # Skip sandbox

        # Fallback to sandbox logic if not an automation repo or if PR failed
        yield {"event": "tool_call", "data": {"tool": "pytest", "code": generated_test}}

        # 5. Execute on Sandbox
        import base64
        encoded_test = base64.b64encode(generated_test.encode('utf-8')).decode('utf-8')
        
        exec_request = ExecutionRequest(
            repo_url="local",
            commit_sha=commit_sha,
            command=f"bash -c 'echo {encoded_test} | base64 -d > managed_test.py && pytest managed_test.py'" 
        )
        
        yield {"event": "reasoning", "data": f"Executing test in isolated sandbox..."}
        exec_response = await self.executor.execute_task(exec_request)
        
        # 6. Capture Logs
        logs = []
        async for log_line in self.executor.stream_logs(exec_response.run_id):
            yield {"event": "log", "data": log_line}
            logs.append(log_line)
        
        # Fetch final status
        final_status = await self.executor.get_run_status(exec_response.run_id)
        
        # 7. Persist Result
        result = RunResult(
            run_id=run_id,
            symbol_name=symbol["name"],
            file_path=symbol["file_path"],
            status=final_status.status,
            test_code=generated_test,
            exit_code=final_status.exit_code,
            log_stream="\n".join(logs),
            error_message=final_status.error_message
        )
        self.session.add(result)
        await self.session.commit()
        
        status_label = "PASSED" if final_status.exit_code == 0 else "FAILED"
        yield {"event": "reasoning", "data": f"Symbol `{symbol['name']}` finished with status: **{status_label}**."}
        
        # 8. Dynamic Suggestion
        if final_status.exit_code != 0:
            yield {"event": "suggestion", "data": {
                "text": f"Test for `{symbol['name']}` failed. Would you like to attempt a self-correction?",
                "actions": [
                    {"label": "Self-Correct", "cmd": f"/fix {symbol['name']}"},
                    {"label": "Ignore", "cmd": "/ignore"}
                ]
            }}

    def _get_code_snippet(self, path: str, start: int, end: int) -> str:
        try:
            with open(path, "r") as f:
                lines = f.readlines()
                return "".join(lines[start-1:end])
        except Exception:
            return "# Code unavailable"

    def _extract_json_block(self, content: str) -> Dict[str, str]:
        
        def _find_json_str(text: str) -> str:
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
            if json_match:
                return json_match.group(1)
            all_json_match = re.search(r'(\{.*\})', text, re.DOTALL)
            return all_json_match.group(1) if all_json_match else text
        
        def _escape_newlines_in_strings(text: str) -> str:
            result = []
            in_string = False
            escape_next = False
            for ch in text:
                if escape_next:
                    result.append(ch)
                    escape_next = False
                    continue
                if ch == '\\' and in_string:
                    escape_next = True
                    result.append(ch)
                    continue
                if ch == '"':
                    in_string = not in_string
                    result.append(ch)
                    continue
                if in_string and ch == '\n':
                    result.append('\\n')
                    continue
                result.append(ch)
            return ''.join(result)
        
        json_str = _find_json_str(content)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
        
        escaped = _escape_newlines_in_strings(json_str)
        try:
            return json.loads(escaped)
        except json.JSONDecodeError:
            pass
        
        # Pre-parse: extract file_path and code via regex as final fallback
        fp_match = re.search(r'"file_path"\s*:\s*"([^"]+)"', json_str)
        code_match = re.search(r'"code"\s*:\s*"(.+)"\s*\}', json_str, re.DOTALL)
        if fp_match and code_match:
            raw_code = code_match.group(1)
            raw_code = raw_code.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
            if raw_code.endswith('"'):
                raw_code = raw_code[:-1]
            return {"file_path": fp_match.group(1), "code": raw_code}
        
        # Final fallback: treat entire content as code
        code = content.strip()
        if code.startswith("```"):
            code = re.sub(r'^```[a-z]*\n', '', code)
            code = re.sub(r'\n```$', '', code)
        return {"file_path": f"test_{int(time.time())}.py", "code": code}
