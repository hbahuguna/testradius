import asyncio
import argparse
import os
from .client import Neo4jClient
from .ingestor import GraphIngestor
from testsquad_core.intelligence.summarizer import SymbolSummarizer
from testsquad_core.analysis.surface import SurfaceDetector
from testsquad_core.analysis.git import GitAnalyzer
from testsquad_core.analysis.coverage import CoberturaParser, CoverageMapper
from testsquad_core.analysis.risk import RiskScorer
from testsquad_core.orchestration.run_orchestrator import RunOrchestrator
from testsquad_core.clients.executor import ExecutorClient
from testsquad_core.persistence.run_models import Run, RunResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from testsquad_shared.persistence.db import SessionLocal

import logging

# (Moved to testsquad_shared.persistence.db)

async def run_indexing(args):
    # Enable debug logging if requested or by default for now
    logging.basicConfig(level=logging.DEBUG if args.summarize else logging.INFO)
    client = Neo4jClient()
    try:
        # Ensure project exists in Neo4j
        client.sync_project(args.project_id, f"Project-{args.project_id}")
        
        if args.summarize:
            summarizer = SymbolSummarizer(client)
            print(f"Summarizing symbols for project {args.project_id}...")
            async for progress in summarizer.summarize_all_missing(args.project_id):
                print(progress)
            print(f"Summarizing test symbols for project {args.project_id}...")
            test_count = await summarizer.summarize_symbols_for_tests(args.project_id)
            print(f"Summarized {test_count} test symbols.")
        elif args.detect_surface:
            detector = SurfaceDetector(client)
            print(f"Detecting surface areas for project {args.project_id}...")
            detector.detect_and_tag(args.project_id)
            print("Surface detection complete.")
        elif args.analyze_git:
            analyzer = GitAnalyzer(args.root)
            print(f"Analyzing git history for project {args.project_id}...")
            metrics = analyzer.get_churn_metrics()
            for path, data in metrics.items():
                client.update_file_git_metrics(path, data["commit_count"], data["author_count"])
            print("Git analysis complete.")
        elif args.analyze_coverage:
            if not args.report_path:
                print("Error: --report-path is required for --analyze-coverage")
                return
            parser = CoberturaParser()
            mapper = CoverageMapper(client)
            print(f"Analyzing coverage report for project {args.project_id} at {args.report_path}...")
            coverage_data = parser.parse_report(args.report_path)
            mapper.map_coverage(args.project_id, coverage_data)
            print("Coverage analysis complete.")
        elif args.calculate_risk:
            scorer = RiskScorer()
            print(f"Calculating risk scores for project {args.project_id}...")
            scored_data = scorer.score_symbols(args.project_id, client)
            client.bulk_update_risk_scores(scored_data)
            print(f"Risk calculation complete. Updated {len(scored_data)} symbols.")
        elif args.run_orchestrator:
            async with SessionLocal() as session:
                executor = ExecutorClient(base_url="http://localhost:8001") # Local dev default
                orchestrator = RunOrchestrator(client, executor, session)
                await orchestrator.run_full_cycle(
                    project_id=args.project_id,
                    commit_sha=args.root # Placeholder
                )
            print("Orchestration cycle complete.")
        else:
            ingestor = GraphIngestor(client, args.project_id)
            print(f"Starting indexing for project {args.project_id} in {args.root}...")
            async for _ in ingestor.ingest_repo_stream(args.root):
                pass
            print("Indexing complete.")
    finally:
        client.close()

def main():
    parser = argparse.ArgumentParser(description="Index a repository into the Repo Brain (Neo4j).")
    parser.add_argument("--root", default=".", help="Root directory of the repository to index.")
    parser.add_argument("--project-id", type=int, required=True, help="SQL Project ID to link the indexing to.")
    parser.add_argument("--summarize", action="store_true", help="Generate semantic summaries for missing symbols.")
    parser.add_argument("--detect-surface", action="store_true", help="Identify high-value entry points (APIs, CLI).")
    parser.add_argument("--analyze-git", action="store_true", help="Extract churn and author metrics from git history.")
    parser.add_argument("--analyze-coverage", action="store_true", help="Map coverage gaps to code symbols.")
    parser.add_argument("--report-path", help="Path to the Cobertura XML coverage report.")
    parser.add_argument("--calculate-risk", action="store_true", help="Synthesize all signals into a Priority Risk Index (PRI).")
    parser.add_argument("--run-orchestrator", action="store_true", help="Start an immutable test run for risky symbols.")
    parser.add_argument("--init-db", action="store_true", help="Initialize database tables.")
    args = parser.parse_args()

    if args.init_db:
        from sqlmodel import SQLModel
        async def init_models():
            async with engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.create_all)
        asyncio.run(init_models())
        print("Database initialized.")
        return

    asyncio.run(run_indexing(args))

if __name__ == "__main__":
    main()
