import os
import json
import re
import asyncio
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Header, BackgroundTasks
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from testsquad_shared.persistence.db import get_session
from sqlalchemy import text, select
from testsquad_shared.persistence.models import Project, StyleCapsule, User, Repository
from testsquad_core.graph.client import Neo4jClient
from .auth import get_current_user
from .github_service import get_github_client, list_repositories, list_pull_requests, get_pr_files
from .intelligence.dependencies import get_llm_client
from .intelligence.summarizer import SymbolSummarizer
from .graph.ingestor import GraphIngestor
from .orchestration.run_orchestrator import RunOrchestrator
from testsquad_shared.models import HealthResponse, LLMRequest
from testsquad_shared.api import TaskStatus
from .persistence.run_models import Run
from testsquad_core.intelligence.registry import llm_registry, initialize_standard_providers
from testsquad_core.intelligence.providers.base import BaseProvider
from testsquad_core.clients.executor import ExecutorClient
from testsquad_shared.logging_config import setup_logging
from sqlalchemy.orm.attributes import flag_modified
from github import Github, Auth
from .analysis.surface import SurfaceDetector
from .analysis.risk import RiskScorer
from .analysis.diff_parser import DiffParser, TestWithScore
from .analysis.scorer import UnifiedScorer
from testsquad_core.features.service import is_feature_enabled, get_project_features, set_project_features
from testsquad_core.test_runner import run_tests

import logging
logger = logging.getLogger("testsquad")

@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_standard_providers()
    from testsquad_shared.persistence.models import SQLModel
    from testsquad_shared.persistence.db import get_engine
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    logger.info("Database tables created/verified")
    yield

app = FastAPI(title="TestSquad - Core Service", lifespan=lifespan)
setup_logging(app)
_cancel_flags: Dict[int, bool] = {}

@app.on_event("startup")
async def startup_event():
    initialize_standard_providers()
    # Create tables if they don't exist
    from testsquad_shared.persistence.models import SQLModel
    from testsquad_shared.persistence.db import get_engine
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    logger.info("Database tables created/verified")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_neo4j():
    client = Neo4jClient()
    try:
        yield client
    finally:
        client.close()

@app.get("/", response_model=HealthResponse)
async def root():
    return HealthResponse(status="online", service="core")

@app.get("/features")
async def get_features():
    """Returns enabled features based on build configuration."""
    import os
    features_path = "/etc/testsquad/features.json"
    try:
        with open(features_path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"vector_matching": False, "llm": False}

@app.get("/health")
async def health(
    session: AsyncSession = Depends(get_session),
    neo4j: Neo4jClient = Depends(get_neo4j)
):
    health_status = {"status": "healthy", "components": {}}

    try:
        await session.execute(text("SELECT 1"))
        health_status["components"]["postgres"] = "connected"
    except Exception as e:
        health_status["components"]["postgres"] = f"error: {str(e)}"
        health_status["status"] = "degraded"

    try:
        neo4j.query("RETURN 1")
        health_status["components"]["neo4j"] = "connected"
    except Exception as e:
        health_status["components"]["neo4j"] = f"error: {str(e)}"
        health_status["status"] = "degraded"

    return health_status

@app.get("/api/system/health")
async def system_health(
    x_github_token: Optional[str] = Header(None),
    session: AsyncSession = Depends(get_session),
    neo4j: Neo4jClient = Depends(get_neo4j)
):
    """
    Detailed system health check for E2E verification.
    """
    health_data = {
        "status": "ok",
        "version": "1.0.1",
        "timestamp": time.time(),
        "database": "ok",
        "neo4j": "ok",
        "github_auth": "valid" if x_github_token else "invalid"
    }

    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        health_data["database"] = "error"

    try:
        neo4j.query("RETURN 1")
    except Exception:
        health_data["neo4j"] = "error"

    return health_data

@app.get("/projects", response_model=List[Project])
async def get_projects(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    result = await session.execute(select(Project).where(Project.owner_id == current_user.id))
    return result.scalars().all()

@app.post("/projects", response_model=Project)
async def create_project(
    project_data: Dict[str, Any],
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = Project(**project_data, owner_id=current_user.id)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project

class FeatureListRequest(BaseModel):
    features: Dict[str, bool]

@app.get("/projects/{project_id}/features")
async def list_project_features(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    project = await _resolve_project(project_id, session)
    if project and project.owner_id and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return await get_project_features(project_id, session)


@app.put("/projects/{project_id}/features")
async def update_project_features(
    project_id: int,
    body: FeatureListRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    project = await _resolve_project(project_id, session)
    if project and project.owner_id and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    await set_project_features(project_id, body.features, session)
    return {"status": "ok", "features": body.features}


async def _resolve_project(project_id: int, session: AsyncSession) -> Optional[Project]:
    """Uniform helper to resolve a project by ID or GitHub ID."""
    result = await session.execute(
        select(Project).where((Project.id == project_id) | (Project.name == str(project_id)))
    )
    return result.scalar_one_or_none()

@app.get("/projects/{project_id}/style-capsule", response_model=StyleCapsule)
async def get_style_capsule(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    project = await _resolve_project(project_id, session)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if project.owner_id and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized for this project")

    result = await session.execute(
        select(StyleCapsule).where(StyleCapsule.project_id == project_id)
    )
    capsule = result.scalar_one_or_none()
    if not capsule:
        capsule = StyleCapsule(project_id=project_id)
        session.add(capsule)
        await session.commit()
        await session.refresh(capsule)
    return capsule

class SyncProjectRequest(BaseModel):
    repo_name: Optional[str] = None
    model_name: Optional[str] = "gemini-1.5-flash"
    use_vector: Optional[bool] = False

class SyncAutomationRequest(BaseModel):
    automation_repo: str

class InstrumentationRunRequest(BaseModel):
    repo_url: Optional[str] = None
    run_fresh: Optional[bool] = False
    language: str = "python"
    testbed_name: Optional[str] = None
    local_path: Optional[str] = None

@app.post("/projects/{project_id}/sync-automation")
async def sync_automation_repo(
    project_id: int,
    request: SyncAutomationRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    neo4j: Neo4jClient = Depends(get_neo4j),
    x_github_token: Optional[str] = Header(None)
):
    """
    Triggers a streaming ingestion of the Automation Repository ASTs into Neo4j.
    """
    proj_result = await session.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one_or_none()
    
    # Enable dynamic creation if not in SQL
    source_name = project.name if project else f"Repo-{project_id}"

    if project and project.owner_id and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to sync this project")
    if not await is_feature_enabled(project_id, "brain_sync", session):
        raise HTTPException(status_code=403, detail="Feature not enabled for this project")

    # Get Github token from request header or environment
    github_token = x_github_token if x_github_token else os.getenv("GITHUB_TOKEN")
        
    if not github_token:
        raise HTTPException(status_code=400, detail="No Github token configured.")

    async def ingest_stream():
        try:
            from testsquad_core.graph.automation_ingestor import AutomationIngestor
            
            # Ensure the project exists in Neo4j before indexing automation files
            neo4j.sync_project(project_id, source_name)
            
            ingestor = AutomationIngestor(neo4j, project_id)
            logger.info(f"Starting Streaming Automation Sync for {request.automation_repo}...")
            
            async for event in ingestor.ingest_repo_stream(request.automation_repo, github_token):
                yield f"data: {json.dumps(event)}\n\n"
            
            yield f"data: {json.dumps({'event': 'status', 'data': {'status': 'COMPLETED'}})}\n\n"
            
        except Exception as e:
            logger.error(f"Automation sync failed: {e}")
            yield f"data: {json.dumps({'event': 'error', 'data': str(e)})}\n\n"

    return StreamingResponse(ingest_stream(), media_type="text/event-stream")

@app.post("/projects/{project_id}/map-tests")
async def map_tests_logic(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    neo4j: Neo4jClient = Depends(get_neo4j),
    llm_client: BaseProvider = Depends(get_llm_client),
    x_llm_model: Optional[str] = Header(None),
    x_use_vector: Optional[str] = Header(None),
    x_use_siamese: Optional[str] = Header(None),
    x_siamese_threshold: Optional[str] = Header(None),
    x_mpnet_threshold: Optional[str] = Header(None),
    x_heuristic_threshold: Optional[str] = Header(None),
    x_use_instrumentation: Optional[str] = Header(None),
    x_test_repo_url: Optional[str] = Header(None),
    x_run_fresh: Optional[str] = Header(None)
):
    """
    Triggers the Intelligence Engine to construct Neo4j edges between Product Nodes and Automation Nodes.
    
    Headers:
    - x-llm-model: LLM model name (e.g., "gemini-1.5-pro") - omit for structural-only
    - x-use-vector: Set to "true" to enable vector matching (no LLM required)
    - x-use-siamese: Set to "true" to enable Siamese network matching (fine-tuned model)
    - x-siamese-threshold: Siamese minimum confidence (default 0.75)
    - x-mpnet-threshold: MPNet minimum confidence (default 0.85)
    - x-heuristic-threshold: Heuristic minimum confidence (default 0.85)
    - x-use-instrumentation: Set to "true" to use runtime instrumentation for test mapping
    - x-test-repo-url: Test repository URL for instrumentation (optional, uses project auto repo if not provided)
    - x-run-fresh: Set to "true" to skip cache and run fresh instrumentation
    """
    proj_result = await session.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one_or_none()
    
    source_name = project.name if project else f"Repo-{project_id}"

    if project and project.owner_id and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to map tests for this project")
    if not await is_feature_enabled(project_id, "test_mapping", session):
        raise HTTPException(status_code=403, detail="Feature not enabled for this project")

    use_siamese = x_use_siamese.lower() == "true" if x_use_siamese else False
    use_instrumentation = x_use_instrumentation.lower() == "true" if x_use_instrumentation else False
    run_fresh = x_run_fresh.lower() == "true" if x_run_fresh else False
    test_repo_url = x_test_repo_url if x_test_repo_url else None
    
    # Parse threshold headers for Siamese
    siamese_thresh = float(x_siamese_threshold) if x_siamese_threshold else None
    mpnet_thresh = float(x_mpnet_threshold) if x_mpnet_threshold else None
    heuristic_thresh = float(x_heuristic_threshold) if x_heuristic_threshold else None
    
    async def map_stream():
        try:
            if use_instrumentation:
                from testsquad_core.instrumentation.pipeline_worker import (
                    run_pipeline, detect_project_language,
                )
                from testsquad_core.instrumentation.testbed_manager import TestbedManager, TestbedConfig
                from testsquad_core.instrumentation.neo4j_store import Neo4jStore

                yield f"data: {json.dumps({'event': 'reasoning', 'data': 'Activating Runtime Instrumentation for precise test-to-symbol mapping...'})}\n\n"

                repo_url = test_repo_url
                if not repo_url and project:
                    project_settings = getattr(project, 'settings', None) or {}
                    repo_url = project_settings.get('auto_repo_url')

                if not repo_url:
                    yield f"data: {json.dumps({'event': 'error', 'data': 'No test repository URL provided. Configure auto-repo or provide x-test-repo-url header.'})}\n\n"
                    return

                yield f"data: {json.dumps({'event': 'reasoning', 'data': 'Cloning repository for language detection...'})}\n\n"

                tm = TestbedManager(base_dir="/tmp")
                clone_config = TestbedConfig(
                    repo_url=repo_url, branch="main",
                    install_command="", test_dir=".",
                )
                tm.register_testbed("detect-lang", clone_config)
                clone_result = tm.clone_testbed("detect-lang", use_cache=not run_fresh)
                if not clone_result.success:
                    yield f"data: {json.dumps({'event': 'error', 'data': f'Clone failed: {clone_result.error_message}'})}\n\n"
                    return

                detected_lang = detect_project_language(clone_result.testbed_path)
                yield f"data: {json.dumps({'event': 'reasoning', 'data': f'Detected language: {detected_lang}'})}\n\n"

                if detected_lang == "playwright":
                    yield f"data: {json.dumps({'event': 'error', 'data': 'Playwright projects with local path not supported via Test Map. Use the Instrumentation tab instead.'})}\n\n"
                    return

                mappings = []
                for event in run_pipeline(
                    project_id=project_id,
                    repo_url=repo_url,
                    local_path=None,
                    language=detected_lang,
                    testbed_name=detected_lang,
                    run_fresh=run_fresh,
                    cancel_flags={},
                ):
                    if event["event"] == "progress":
                        yield f"data: {json.dumps({'event': 'reasoning', 'data': event['data']})}\n\n"
                    elif event["event"] == "error":
                        yield f"data: {json.dumps({'event': 'error', 'data': event['data']})}\n\n"
                    elif event["event"] == "status":
                        yield f"data: {json.dumps(event)}\n\n"
                    elif event["event"] == "mappings":
                        mappings = event["data"]

                if not mappings:
                    yield f"data: {json.dumps({'event': 'error', 'data': 'No mappings generated from instrumentation'})}\n\n"
                    return

                store = Neo4jStore(neo4j_client=neo4j)
                mapping_count = store.store_mappings(mappings, project_id=project_id)
                yield f"data: {json.dumps({'event': 'progress', 'data': f'Stored {mapping_count} test-symbol mappings in Neo4j'})}\n\n"
                yield f"data: {json.dumps({'event': 'status', 'data': {'status': 'COMPLETED', 'mode': 'instrumentation', 'mappings': mapping_count}})}\n\n"
                return
                
            if use_siamese:
                from testsquad_core.intelligence.siamese_config import SiameseConfig
                from testsquad_core.intelligence.siamese_mapper import SiameseMapper
                yield f"data: {json.dumps({'event': 'reasoning', 'data': 'Activating Siamese network for test mapping...'})}\n\n"
                
                config = SiameseConfig(
                    siamese_threshold=siamese_thresh,
                    mpnet_threshold=mpnet_thresh,
                    heuristic_threshold=heuristic_thresh
                )
                mapper = SiameseMapper(neo4j, config=config)
                
                yield f"data: {json.dumps({'event': 'progress', 'data': f'Siamese: {config.siamese_threshold}, MPNet: {config.mpnet_threshold}, Heuristic: {config.heuristic_threshold}'})}\n\n"
                
                async for event in mapper.map_tests(project_id, model="siamese"):
                    yield f"data: {json.dumps(event)}\n\n"
                    
                yield f"data: {json.dumps({'event': 'status', 'data': {'status': 'COMPLETED', 'mode': 'siamese'}})}\n\n"
            else:
                from testsquad_core.intelligence.test_mapper import TestMapper
                yield f"data: {json.dumps({'event': 'reasoning', 'data': 'Activating Intelligence Engine to bridge Production ASTs to Automation Signatures...'})}\n\n"
                
                skip_llm = os.getenv("SKIP_LLM_MAPPING", "false").lower() == "true"
                try:
                    use_vector = x_use_vector.lower() == "true" if x_use_vector else False
                except AttributeError:
                    use_vector = False
                mapper = TestMapper(neo4j, llm_client, skip_llm=skip_llm, use_vector=use_vector)
                raw_model = x_llm_model if x_llm_model else "gemini-1.5-pro"
                model_name = raw_model.strip().strip(",")
                
                async for update in mapper.map_tests(project_id, model_name):
                    yield f"data: {json.dumps({'event': 'reasoning', 'data': update})}\n\n"
                
                yield f"data: {json.dumps({'event': 'status', 'data': {'status': 'COMPLETED'}})}\n\n"
        except Exception as e:
            logger.error(f"Mapping failed: {e}")
            yield f"data: {json.dumps({'event': 'error', 'data': str(e)})}\n\n"

    return StreamingResponse(map_stream(), media_type="text/event-stream")


@app.get("/projects/{project_id}/training-data")
async def get_training_data(
    project_id: int,
    min_confidence: float = 0.6,
    limit: int = 5000,
    include_negatives: bool = True,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    neo4j: Neo4jClient = Depends(get_neo4j)
):
    """Export training data CSV for Siamese network fine-tuning."""
    from testsquad_core.intelligence.training_exporter import TrainingExporter
    from fastapi.responses import StreamingResponse
    import io
    import csv
    from datetime import datetime
    
    project = await _resolve_project(project_id, session)
    
    if not project:
        check_query = "MATCH (p:Project {sql_id: $pid}) RETURN p"
        if not neo4j.query(check_query, {"pid": project_id}):
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    try:
        exporter = TrainingExporter(neo4j=neo4j)
        
        # Get positive pairs
        rows = exporter.export_candidate_pairs(project_id, min_confidence, limit)
        
        # Get hard negatives if requested
        if include_negatives:
            negatives = exporter.export_hard_negatives(project_id, max_negatives=limit // 2)
            rows.extend(negatives)
        
        # Generate CSV manually
        if rows:
            output = io.StringIO()
            fieldnames = list(rows[0].keys())
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            csv_content = output.getvalue()
        else:
            csv_content = "sym_id,sym_path,sym_summary,test_id,test_path,test_summary,confidence,source,reasoning,label\n"
        
        filename = f"training-data-{project_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.csv"
        
        return StreamingResponse(
            iter([csv_content]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"Training data export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/projects/{project_id}/vector-map-tests")
async def vector_map_tests(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    neo4j: Neo4jClient = Depends(get_neo4j),
    x_threshold: Optional[float] = Header(0.75, ge=0.0, le=1.0),
    x_mapping_backend: Optional[str] = Header("vector")
):
    """
    Vector-based test mapping using multi-signal candidate generation.
    
    - POST /projects/{project_id}/vector-map-tests
    - Returns SSE stream with progress events
    - Header X-Threshold: minimum confidence (default 0.75)
    - Header X-Mapping-Backend: vector|llm (default: vector)
    """
    # Validate threshold
    if x_threshold is None or not (0.0 <= x_threshold <= 1.0):
        raise HTTPException(status_code=400, detail="Invalid threshold. Must be between 0.0 and 1.0")
    
    # Validate backend
    valid_backends = ["vector", "llm"]
    backend = x_mapping_backend.lower() if x_mapping_backend else "vector"
    if backend not in valid_backends:
        raise HTTPException(status_code=400, detail=f"Invalid backend. Must be one of: {valid_backends}")
    
    # Check project exists
    proj_result = await session.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one_or_none()
    
    if project and project.owner_id and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized for this project")
    if not await is_feature_enabled(project_id, "test_mapping", session):
        raise HTTPException(status_code=403, detail="Feature not enabled for this project")

    if not project:
        # Try resolving by neo4j
        check_query = "MATCH (p:Project {sql_id: $pid}) RETURN p"
        if not neo4j.query(check_query, {"pid": project_id}):
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    async def vector_map_stream():
        try:
            from testsquad_core.intelligence.vector_mapper import VectorMapper
            from testsquad_core.intelligence.embedder import Embedder
            
            source_name = project.name if project else f"Repo-{project_id}"
            yield f"data: {json.dumps({'event': 'reasoning', 'data': f'Starting vector-based test mapping for {source_name}...'})}\n\n"
            
            # Initialize VectorMapper with Embedder
            embedder = Embedder()
            mapper = VectorMapper(neo4j=neo4j, embedder=embedder)
            
            # Emit threshold info
            yield f"data: {json.dumps({'event': 'progress', 'data': f'Using confidence threshold: {x_threshold}'})}\n\n"
            
            # Stage 1: Generate candidates
            yield f"data: {json.dumps({'event': 'progress', 'data': 'Generating candidate pairs...'})}\n\n"
            candidates = mapper.generate_candidates(project_id)
            yield f"data: {json.dumps({'event': 'progress', 'data': f'Generated {len(candidates)} candidate pairs'})}\n\n"
            
            # Stage 2: Vector matching
            yield f"data: {json.dumps({'event': 'progress', 'data': 'Computing vector similarities...'})}\n\n"
            matches = mapper._match_vectors(candidates, threshold=x_threshold)
            yield f"data: {json.dumps({'event': 'progress', 'data': f'Matched {len(matches)} pairs above threshold {x_threshold}'})}\n\n"
            
            # Stage 3: Create edges
            yield f"data: {json.dumps({'event': 'progress', 'data': 'Creating EVIDENCE edges...'})}\n\n"
            edges_created = mapper._create_edges(matches, project_id)
            yield f"data: {json.dumps({'event': 'progress', 'data': f'Created {edges_created} edges in Neo4j'})}\n\n"
            
            # Final status
            yield f"data: {json.dumps({'event': 'status', 'data': {'status': 'COMPLETED', 'candidates': len(candidates), 'matches': len(matches), 'edges': edges_created}})}\n\n"
            
        except Exception as e:
            logger.error(f"Vector mapping failed: {e}")
            yield f"data: {json.dumps({'event': 'error', 'data': str(e)})}\n\n"
            yield f"data: {json.dumps({'event': 'status', 'data': {'status': 'FAILED', 'error': str(e)}})}\n\n"
    
    return StreamingResponse(vector_map_stream(), media_type="text/event-stream")


@app.get("/projects/{project_id}/mapping-accuracy")
async def get_mapping_accuracy(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    neo4j: Neo4jClient = Depends(get_neo4j),
    limit: int = 50
):
    """
    Get accuracy metrics for mapping results.
    
    Compares Siamese vs Vector mappings and returns:
    - Total mappings by each model
    - Overlap (agreements/disagreements)
    - Confidence distributions
    - Threshold pass rates
    """
    from testsquad_core.intelligence.model_compare import ModelCompare
    from testsquad_core.intelligence.siamese_config import SiameseConfig
    
    project = await _resolve_project(project_id, session)
    if not project:
        check_query = "MATCH (p:Project {sql_id: $pid}) RETURN p"
        if not neo4j.query(check_query, {"pid": project_id}):
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    try:
        config = SiameseConfig()
        compare = ModelCompare(neo4j, config=config)
        
        project_stats = compare.compare_project(project_id, limit=limit)
        overlap_stats = compare.get_overlap(project_id)
        
        return {
            "project_id": project_id,
            "project_stats": project_stats,
            "overlap": overlap_stats,
            "model": "siamese_vs_vector"
        }
    except Exception as e:
        logger.error(f"Accuracy validation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/projects/{project_id}/siamese-map")
async def siamese_map_tests(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    neo4j: Neo4jClient = Depends(get_neo4j),
    x_siamese_threshold: Optional[float] = Header(0.5, ge=0.0, le=1.0),
    x_mpnet_threshold: Optional[float] = Header(0.5, ge=0.0, le=1.0),
    x_heuristic_threshold: Optional[float] = Header(0.5, ge=0.0, le=1.0),
    x_model: Optional[str] = Header("siamese")
):
    """
    Siamese network-based test mapping using fine-tuned model.
    
    - POST /projects/{project_id}/siamese-map
    - Returns SSE stream with progress events
    - Header X-Siamese-Threshold: minimum Siamese confidence (default 0.75)
    - Header X-Mpnet-Threshold: minimum MPNet fallback confidence (default 0.85)
    - Header X-Model: siamese|mpnet|both (default: siamese)
    
    Combines multi-signal candidate generation with Siamese embeddings.
    Uses max fusion: final_confidence = max(siamese, mpnet, heuristic)
    """
    from testsquad_core.intelligence.siamese_config import SiameseConfig
    from testsquad_core.intelligence.siamese_mapper import SiameseMapper
    
    # Validate thresholds
    if x_siamese_threshold is None or not (0.0 <= x_siamese_threshold <= 1.0):
        raise HTTPException(status_code=400, detail="Invalid siamese_threshold. Must be between 0.0 and 1.0")
    if x_mpnet_threshold is None or not (0.0 <= x_mpnet_threshold <= 1.0):
        raise HTTPException(status_code=400, detail="Invalid mpnet_threshold. Must be between 0.0 and 1.0")
    
    # Validate model
    valid_models = ["siamese", "mpnet", "both"]
    model = x_model.lower() if x_model else "siamese"
    if model not in valid_models:
        raise HTTPException(status_code=400, detail=f"Invalid model. Must be one of: {valid_models}")
    
    # Check project exists
    proj_result = await session.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one_or_none()
    
    if project and project.owner_id and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized for this project")
    if not await is_feature_enabled(project_id, "test_mapping", session):
        raise HTTPException(status_code=403, detail="Feature not enabled for this project")

    if not project:
        check_query = "MATCH (p:Project {sql_id: $pid}) RETURN p"
        if not neo4j.query(check_query, {"pid": project_id}):
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    async def siamese_map_stream():
        try:
            source_name = project.name if project else f"Repo-{project_id}"
            yield f"data: {json.dumps({'event': 'reasoning', 'data': f'Starting Siamese test mapping for {source_name}...'})}\n\n"
            
            # Initialize config with thresholds from headers
            config = SiameseConfig(
                siamese_threshold=x_siamese_threshold,
                mpnet_threshold=x_mpnet_threshold,
                heuristic_threshold=x_heuristic_threshold
            )
            
            # Initialize SiameseMapper
            mapper = SiameseMapper(neo4j, config=config)
            
            # Emit threshold info
            yield f"data: {json.dumps({'event': 'progress', 'data': f'Siamese: {x_siamese_threshold}, MPNet: {x_mpnet_threshold}, Heuristic: {x_heuristic_threshold}'})}\n\n"
            yield f"data: {json.dumps({'event': 'progress', 'data': f'Model mode: {model}'})}\n\n"
            
            # Run the mapping pipeline
            for event in mapper.map_tests(project_id, model=model):
                yield f"data: {json.dumps(event)}\n\n"
            
        except Exception as e:
            logger.error(f"Siamese mapping failed: {e}")
            yield f"data: {json.dumps({'event': 'error', 'data': str(e)})}\n\n"
            yield f"data: {json.dumps({'event': 'status', 'data': {'status': 'FAILED', 'error': str(e)}})}\n\n"
    
    return StreamingResponse(siamese_map_stream(), media_type="text/event-stream")

class TestMappingEntry(BaseModel):
    product_symbol: str
    product_file: str
    test_symbol: str
    test_file: str
    confidence: float
    reasoning: str
    status: str

class TestMappingUpdate(BaseModel):
    mappings: List[TestMappingEntry]

@app.get("/projects/{project_id}/test-mapping", response_model=List[TestMappingEntry])
async def get_test_mapping(
    project_id: int,
    limit: int = 50,
    offset: int = 0,
    query: Optional[str] = None,
    source: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    neo4j: Neo4jClient = Depends(get_neo4j)
):
    # Attempt to resolve project by PostgreSQL PK or GitHub ID (fallback)
    project = await _resolve_project(project_id, session)
    
    # If not found in SQL, we still allow proceeding if it exists in Neo4j (demo-friendly)
    if not project:
        logger.warning(f"Project {project_id} not found in SQL, checking Neo4j only.")

    cypher_filter = ""
    params = {"pid": project_id, "limit": limit, "offset": offset}
    if query:
        cypher_filter = "AND (toLower(s.name) CONTAINS toLower($q) OR toLower(s.file_path) CONTAINS toLower($q) OR toLower(ts.name) CONTAINS toLower($q))"
        params["q"] = query

    rel_types = ['EVIDENCE', 'APPROVED_TEST']
    source_filter = "AND r.source = $source " if source else ""

    rel_types_str = ", ".join(f"'{t}'" for t in rel_types)
    cypher_query = f"""
    MATCH (s:Symbol)-[r]-(ts:TestSymbol)
    WHERE type(r) IN [{rel_types_str}] {source_filter}{cypher_filter}
      AND (
        s.project_id = $pid
        OR EXISTS {{ MATCH (p:Project {{sql_id: $pid}})-[:CONTAINS]->(:File)-[:DEFINES]->(s) }}
      )
    RETURN s.name as p_sym, s.file_path as p_file, ts.name as t_sym, ts.file_path as t_file,
           r.confidence as conf, r.reasoning as reason, type(r) as status
    ORDER BY r.confidence DESC
    SKIP $offset
    LIMIT $limit
    """
    if source:
        params["source"] = source
    results = neo4j.query(cypher_query, params)
    
    mappings = []
    for row in results:
        mappings.append(TestMappingEntry(
            product_symbol=row["p_sym"],
            product_file=row["p_file"],
            test_symbol=row["t_sym"],
            test_file=row["t_file"],
            confidence=float(row.get("conf") if row.get("conf") is not None else 0.0),
            reasoning=row.get("reason") or "",
            status=row["status"]
        ))
    return mappings

class CommunitySymbol(BaseModel):
    name: str
    type: str
    file_path: str
    priority: Optional[float] = None

class CommunityResponse(BaseModel):
    id: int
    symbols: List[CommunitySymbol]

@app.get("/projects/{project_id}/communities", response_model=List[CommunityResponse])
async def get_project_communities(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    neo4j: Neo4jClient = Depends(get_neo4j)
):
    # Attempt to resolve project by PostgreSQL PK or GitHub ID (fallback)
    project = await _resolve_project(project_id, session)
    if project and project.owner_id and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this project")
    if not await is_feature_enabled(project_id, "communities", session):
        raise HTTPException(status_code=403, detail="Feature not enabled for this project")

    results = neo4j.get_communities(project_id)
    communities = []
    for row in results:
        syms = []
        for s in row.get("symbols", []):
            syms.append(CommunitySymbol(
                name=s.get("name"),
                type=s.get("type", "unknown"),
                file_path=s.get("file_path", ""),
                priority=s.get("priority")
            ))
        communities.append(CommunityResponse(id=row["id"], symbols=syms))
    
    return communities

@app.get("/projects/{project_id}/communities/graph")
async def get_project_communities_graph(
    project_id: int,
    limit: int = 500,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    neo4j: Neo4jClient = Depends(get_neo4j)
):
    project = await _resolve_project(project_id, session)
    if project and project.owner_id and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this project")
    if not await is_feature_enabled(project_id, "communities", session):
        raise HTTPException(status_code=403, detail="Feature not enabled for this project")

    return neo4j.get_community_graph(project_id, limit=limit, offset=offset)

@app.put("/projects/{project_id}/test-mapping")
async def update_test_mapping(
    project_id: int,
    update_data: TestMappingUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    neo4j: Neo4jClient = Depends(get_neo4j)
):
    # Attempt to resolve project by PostgreSQL PK or GitHub ID (fallback)
    proj_result = await session.execute(
        select(Project).where((Project.id == project_id) | (Project.name == str(project_id)) | (Project.name == f"Repo-{project_id}"))
    )
    if not proj_result.scalar_one_or_none():
        logger.warning(f"Project {project_id} not found in SQL during manual mapping update.")

    for m in update_data.mappings:
        if m.status == 'APPROVED_TEST':
            # Remove EVIDENCE edge, create APPROVED edge
            neo4j.query("""
            MATCH (ts:TestSymbol {name: $t_sym})-[r:EVIDENCE]->(s:Symbol {name: $p_sym, file_path: $p_file})
            DELETE r
            MERGE (s)-[:APPROVED_TEST]->(ts)
            """, {"p_sym": m.product_symbol, "p_file": m.product_file, "t_sym": m.test_symbol})
        elif m.status == 'REJECTED':
            neo4j.query("""
            MATCH (s:Symbol {name: $p_sym, file_path: $p_file})-[r]-(ts:TestSymbol {name: $t_sym})
            WHERE type(r) IN ['EVIDENCE', 'APPROVED_TEST']
            DELETE r
            """, {"p_sym": m.product_symbol, "p_file": m.product_file, "t_sym": m.test_symbol})
            
    return {"status": "success"}

@app.post("/projects/{project_id}/sync")
async def sync_project_brain(
    project_id: int,
    request: Optional[SyncProjectRequest] = None,
    x_github_token: Optional[str] = Header(None),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    neo4j: Neo4jClient = Depends(get_neo4j),
    llm_client: BaseProvider = Depends(get_llm_client)
):
    """
    Triggers a full streaming re-indexing of the project repository into Neo4j.
    Updates symbols and relationships in the foreground via StreamingResponse SSEs.
    """
    proj_result = await session.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one_or_none()
    
    # If project doesn't exist in SQL, allow dynamic creation in Neo4j using the provided ID
    source_name = project.name if project else f"Repo-{project_id}"
    
    if project and project.owner_id and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to sync this project")
    if not await is_feature_enabled(project_id, "brain_sync", session):
        raise HTTPException(status_code=403, detail="Feature not enabled for this project")

    async def sync_stream():
        try:
            from testsquad_core.graph.ingestor import GraphIngestor
            from testsquad_core.utils.repo_manager import RepositoryManager
            
            repo_manager = RepositoryManager()
            
            # Ensure the project exists in Neo4j
            neo4j.sync_project(project_id, source_name)
            if request and request.repo_name:
                repo_name = request.repo_name
            else:
                repo_result = await session.execute(
                    select(Repository).where(Repository.project_id == project_id)
                )
                repository = repo_result.scalars().first()
                if repository:
                    repo_name = repository.url
            
            if not repo_name:
                repo_root = os.getenv("WORKSPACE_ROOT")
                if not repo_root:
                    yield f"data: {json.dumps({'event': 'error', 'data': 'No repository configured and WORKSPACE_ROOT env var not set'})}\n\n"
                    return
                target_name = "Local Workspace"
            else:
                target_name = repo_name
                yield f"data: {json.dumps({'event': 'reasoning', 'data': f'Architecting dynamic workspace for {target_name}...'})}\n\n"
                try:
                    repo_root = await repo_manager.ensure_local_repo(repo_name, github_token=x_github_token)
                except Exception as e:
                    yield f"data: {json.dumps({'event': 'error', 'data': f'Workspace provisioning failed: {str(e)}'})}\n\n"
                    return

            logger.info(f"Starting Streaming Project Brain Sync for {source_name} (Target: {target_name})...")
            
            # Start Ingestion
            ingestor = GraphIngestor(neo4j, project_id)
            async for event in ingestor.ingest_repo_stream(repo_root):
                yield f"data: {json.dumps(event)}\n\n"
            
            # Trigger automated summarization for missing symbols
            try:
                from testsquad_core.intelligence.summarizer import SymbolSummarizer
                model_to_use = request.model_name if request and request.model_name else "gemini-1.5-flash"
                summarizer = SymbolSummarizer(neo4j, llm_client=llm_client, model_name=model_to_use)
                yield f"data: {json.dumps({'event': 'log', 'data': f'✨ Generating semantic summaries using {model_to_use}...'})}\n\n"
                async for progress in summarizer.summarize_all_missing(project_id, repo_root):
                    yield f"data: {json.dumps({'event': 'reasoning', 'data': progress})}\n\n"
            except Exception as se:
                logger.warning(f"Summarization failed: {se}")
            
            # --- NEW: Automated Surface Detection & Risk Scoring ---
            try:
                yield f"data: {json.dumps({'event': 'log', 'data': '🔍 Running Surface Detection...'})}\n\n"
                surface_detector = SurfaceDetector(neo4j)
                surface_detector.detect_and_tag(project_id)
                
                yield f"data: {json.dumps({'event': 'log', 'data': '⚖️ Scoring Symbol Risks (PRI)...'})}\n\n"
                risk_scorer = RiskScorer()
                scored_data = risk_scorer.score_symbols(project_id, neo4j)
                if scored_data:
                    neo4j.bulk_update_risk_scores(scored_data)
                    yield f"data: {json.dumps({'event': 'log', 'data': f'✅ Calculated Risk Index for {len(scored_data)} symbols.'})}\n\n"
            except Exception as ae:
                logger.error(f"Analysis phase failed: {ae}")
                yield f"data: {json.dumps({'event': 'log', 'data': f'⚠️ Analysis phase incomplete: {str(ae)}'})}\n\n"

            # --- NEW: Automated Test Mapping ---
            try:
                from testsquad_core.intelligence.test_mapper import TestMapper
                yield f"data: {json.dumps({'event': 'log', 'data': '🧠 Bridging Knowledge Gap: Automating Test Mapping...'})}\n\n"
                skip_llm = os.getenv("SKIP_LLM_MAPPING", "false").lower() == "true"
                try:
                    use_vector = request.use_vector if request else False
                except AttributeError:
                    use_vector = False
                mapper = TestMapper(neo4j, llm_client, skip_llm=skip_llm, use_vector=use_vector)
                model_to_use = request.model_name if request and request.model_name else "gemini-1.5-flash"
                async for update in mapper.map_tests(project_id, model_to_use):
                    yield f"data: {json.dumps({'event': 'log', 'data': update})}\n\n"
            except Exception as me:
                logger.error(f"Mapping phase failed: {me}")
                yield f"data: {json.dumps({'event': 'log', 'data': f'⚠️ Mapping phase incomplete: {str(me)}'})}\n\n"

            yield f"data: {json.dumps({'event': 'log', 'data': f'✅ Knowledge Graph structure synced for {source_name}.'})}\n\n"
            yield f"data: {json.dumps({'event': 'status', 'data': {'status': 'COMPLETED'}})}\n\n"
        except Exception as e:
            logger.error(f"Sync failed: {e}", exc_info=True)
            yield f"data: {json.dumps({'event': 'error', 'data': str(e)})}\n\n"

    return StreamingResponse(sync_stream(), media_type="text/event-stream")

@app.post("/projects/{project_id}/analyze")
async def analyze_project(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    neo4j: Neo4jClient = Depends(get_neo4j)
):
    """
    Manually triggers surface detection and risk scoring for an already indexed project.
    """
    project = await _resolve_project(project_id, session)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if project.owner_id and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized for this project")

    try:
        # 1. Surface Detection
        surface_detector = SurfaceDetector(neo4j)
        surface_detector.detect_and_tag(project_id)
        
        # 2. Risk Scoring
        risk_scorer = RiskScorer()
        scored_data = risk_scorer.score_symbols(project_id, neo4j)
        if scored_data:
            neo4j.bulk_update_risk_scores(scored_data)
            
        return {
            "status": "success", 
            "message": f"Surface and Risk analysis complete. Scored {len(scored_data)} symbols."
        }
    except Exception as e:
        logger.error(f"Manual analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/projects/{project_id}/analyze-impact")
async def analyze_impact(
    project_id: int,
    diff_request: Dict[str, Any],
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    neo4j: Neo4jClient = Depends(get_neo4j)
):
    """
    Analyze impact of a PR diff on test coverage.
    
    Body:
        diff: str - PR diff text in unified format
        use_vector: bool - Use vector matching (requires ML deps, default: false)
        
    Returns ranked list of impacted tests with confidence and risk scores.
    """
    project = await _resolve_project(project_id, session)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if project.owner_id and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized for this project")
    
    diff_text = diff_request.get("diff", "")
    use_vector = diff_request.get("use_vector", False)
    test_method_map_path = diff_request.get("test_method_map_path", "")
    source_root = diff_request.get("source_root", "")
    
    if not diff_text:
        raise HTTPException(status_code=400, detail="Diff text is required")
    
    try:
        # 1. Parse the diff
        scorer = UnifiedScorer()
        parser = DiffParser(neo4j_client=neo4j, scorer=scorer)
        file_changes = parser.parse_diff(diff_text)
        
        if not file_changes:
            return {"tests": [], "message": "No changes detected in diff"}
        
        # 2. Map changed lines to symbols
        all_symbols = []
        for fc in file_changes:
            if fc.is_binary or fc.is_deleted:
                continue
            all_changed_lines = list(fc.added_lines) + list(fc.removed_lines)
            if all_changed_lines:
                symbols = parser.map_lines_to_symbols(fc.path, all_changed_lines, project_id)
                all_symbols.extend(symbols)
        
        if not all_symbols:
            # Fallback: use file-level matching
            for fc in file_changes:
                if not fc.is_binary:
                    all_symbols.append({
                        "symbol_name": fc.path.split("/")[-1],
                        "file_path": fc.path,
                        "start_line": 1,
                        "end_line": 100
                    })
        
        # 3. Initialize embedder if requested and available
        embedder = None
        if use_vector:
            try:
                from testsquad_core.intelligence.embedder import Embedder
                embedder = Embedder()
                embedder.load_model()
            except Exception as e:
                logger.warning(f"Embedder not available: {e}")
        
        # 4. Get impacted tests from Neo4j
        impacted_tests = parser.get_impact_tests(
            all_symbols, 
            project_id=project_id,
            embedder=embedder,
            max_hops=2,
            top_k=20
        )
        
        tests = []
        if impacted_tests:
            tests = [
                {
                    "name": t.test_name,
                    "file": t.test_file,
                    "confidence": t.confidence,
                    "reason": t.reason,
                    "risk_score": t.risk_score,
                    "evidence_count": len(t.reason.split(";")) if t.reason else 0,
                }
                for t in impacted_tests
            ]
        
        # 5. Fallback: file-based TestMethodMap when Neo4j returns nothing
        if not tests and test_method_map_path and source_root:
            if os.path.exists(test_method_map_path) and os.path.isdir(source_root):
                from testsquad_core.instrumentation.diff_parser import DiffParser as FileDiffParser
                file_result = FileDiffParser.resolve_impacted_tests(
                    diff_text=diff_text,
                    test_method_map_path=test_method_map_path,
                    source_root=source_root,
                )
                tests = [
                    {
                        "name": t.test_file,
                        "file": t.test_file,
                        "confidence": 1.0,
                        "reason": ";".join(t.impacted_symbols) if t.impacted_symbols else "file_fallback",
                        "risk_score": 1.0,
                        "evidence_count": len(t.impacted_symbols),
                    }
                    for t in file_result.impacted_tests
                ]
                return {"tests": tests, "source": "test_method_map", "total_tests": file_result.total_tests, "selected_count": file_result.selected_count}
        
        return {"tests": tests}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Impact analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/projects/{project_id}/analyze-pr")
async def analyze_pr(
    project_id: int,
    pr_data: Dict[str, Any],
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    neo4j: Neo4jClient = Depends(get_neo4j),
    x_github_token: Optional[str] = Header(None)
):
    """
    Analyze a GitHub PR for test impact using the orchestrator's symbol selection
    and existing test mapping reuse.

    Body:
        full_name: str - GitHub repo full name (owner/repo)
        pr_number: int - PR number
        commit_sha: str - Commit SHA being analyzed
        file_paths: Optional[List[str]] - Override PR file paths (fetched from GitHub if omitted)

    Returns selected symbols and their existing/reused test mappings.
    """
    project = await _resolve_project(project_id, session)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.owner_id and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized for this project")

    full_name = pr_data.get("full_name")
    pr_number = pr_data.get("pr_number")
    commit_sha = pr_data.get("commit_sha", "main")
    file_paths_override = pr_data.get("file_paths")
    github_token = x_github_token or os.getenv("GITHUB_TOKEN")

    if not full_name or not pr_number:
        raise HTTPException(status_code=400, detail="full_name and pr_number are required")

    # 1. Resolve PR file paths (from explicit list or GitHub API)
    pr_files = file_paths_override
    if not pr_files and github_token:
        try:
            g = Github(auth=Auth.Token(github_token))
            pr_files = await get_pr_files(g, full_name, pr_number)
            logger.info(f"Fetched {len(pr_files)} PR files from GitHub for {full_name}#{pr_number}")
        except Exception as e:
            logger.warning(f"Could not resolve PR files from GitHub: {e}")
            pr_files = []

    if not pr_files:
        logger.warning(f"No PR files available for {full_name}#{pr_number} — analysis will be project-wide")
    else:
        logger.info(f"Analyzing PR #{pr_number} in {full_name} — {len(pr_files)} changed files")

    # 2. Select risky symbols from Neo4j (same dual-query logic as the orchestrator)
    if pr_files:
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

    params = {"project_id": project_id, "file_paths": pr_files or []}
    ingestor_results = neo4j.query(ingestor_query, params)
    sm_results = neo4j.query(store_mappings_query, params)

    combined = ingestor_results + sm_results
    combined.sort(key=lambda r: -r["pri"])

    seen = set()
    symbols = []
    for row in combined:
        key = (row["name"], row["file_path"])
        if key not in seen:
            seen.add(key)
            symbols.append(row)
            if len(symbols) >= 10:
                break

    logger.info(f"Selected {len(symbols)} risky symbols for PR #{pr_number}")

    # 3. For each symbol, check existing test mappings (EVIDENCE edges)
    selected_tests = []
    for sym in symbols:
        existing = neo4j.query("""
            MATCH (s:Symbol {name: $name, file_path: $path})
            OPTIONAL MATCH (ts:TestSymbol)-[:EVIDENCE]->(s)
            WITH COLLECT(DISTINCT ts) as all_tss
            UNWIND all_tss as ts
            WITH ts WHERE ts IS NOT NULL
            RETURN DISTINCT ts.name as test_name, ts.file_path as test_file
        """, {"name": sym["name"], "path": sym["file_path"]})

        tests_for_symbol = [
            {
                "test_name": t["test_name"],
                "test_file": t["test_file"],
            }
            for t in existing
        ]

        if tests_for_symbol:
            selected_tests.append({
                "symbol_name": sym["name"],
                "symbol_file": sym["file_path"],
                "symbol_summary": sym.get("summary", ""),
                "symbol_type": sym.get("type", ""),
                "priority_risk_index": sym["pri"],
                "existing_tests": tests_for_symbol,
            })

    total_tests_reused = sum(len(s["existing_tests"]) for s in selected_tests)
    logger.info(f"Found {total_tests_reused} reusable tests across {len(selected_tests)} symbols for PR #{pr_number}")

    return {
        "project_id": project_id,
        "full_name": full_name,
        "pr_number": pr_number,
        "commit_sha": commit_sha,
        "pr_files_analyzed": len(pr_files) if pr_files else 0,
        "symbols_selected": len(symbols),
        "tests_selected": len(selected_tests),
        "total_tests_reused": total_tests_reused,
        "results": selected_tests,
    }


@app.post("/projects/{project_id}/execute-tests")
async def execute_selected_tests(
    project_id: int,
    exec_data: Dict[str, Any],
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    x_github_token: Optional[str] = Header(None),
):
    """
    Execute the selected tests for a PR and return results.

    Body:
        owner: str - GitHub owner
        repo: str - GitHub repo name
        pr_number: int - PR number
        commit_sha: str - Commit SHA or branch
        github_token: str - GitHub token for cloning
        tests: List[{name: str, file: str}] - Tests to execute

    Returns per-test pass/fail results.
    """
    project = await _resolve_project(project_id, session)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.owner_id and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized for this project")

    owner = exec_data.get("owner")
    repo = exec_data.get("repo")
    pr_number = exec_data.get("pr_number")
    commit_sha = exec_data.get("commit_sha", "main")
    github_token = exec_data.get("github_token") or x_github_token
    tests = exec_data.get("tests", [])

    if not owner or not repo or not pr_number:
        raise HTTPException(status_code=400, detail="owner, repo, and pr_number are required")
    if not tests:
        raise HTTPException(status_code=400, detail="At least one test is required")
    if not github_token:
        raise HTTPException(status_code=400, detail="GitHub token is required for cloning")

    repo_url = f"https://github.com/{owner}/{repo}.git"
    result = await run_tests(repo_url, commit_sha, github_token, tests)

    return {
        "project_id": project_id,
        "full_name": f"{owner}/{repo}",
        "pr_number": pr_number,
        "commit_sha": commit_sha,
        **result,
    }


@app.post("/projects/{project_id}/instrumentation/run")
async def run_instrumentation(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    neo4j: Neo4jClient = Depends(get_neo4j),
    request: Optional[InstrumentationRunRequest] = None,
    x_github_token: Optional[str] = Header(None),
):
    """
    Run instrumentation-based TIA for a project.

    This endpoint:
    1. Clones the test repository
    2. Runs tests with coverage instrumentation
    3. Builds test-symbol map in Neo4j
    4. Returns impacted tests for code changes

    Accepts optional JSON body with:
      - repo_url: override the default testbed URL
      - run_fresh: skip cache, force fresh clone
      - language: "python" (default), "typescript", or "playwright"
      - testbed_name: for TypeScript (blacktrigram, zod, hono) or Playwright (testradius)
      - local_path: filesystem path for local Playwright projects

    For Python demo (no repo_url), uses py-key-value repo.
    For TypeScript demo (no repo_url), uses blacktrigram testbed.
    For Playwright, a local_path is required (or TESTRADIUS_LOCAL_PATH env var).
    """
    project = await _resolve_project(project_id, session)

    if project and project.owner_id and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if not await is_feature_enabled(project_id, "instrumentation", session):
        raise HTTPException(status_code=403, detail="Feature not enabled for this project")

    if not project:
        logger.warning(f"Project {project_id} not found in SQL, proceeding with Neo4j only.")

    async def run_instrumentation_worker():
        try:
            from testsquad_core.instrumentation.pipeline_worker import run_pipeline
            from testsquad_core.instrumentation.neo4j_store import Neo4jStore

            request_language = (request and request.language) or "python"
            request_testbed = request and request.testbed_name

            if not request_language:
                request_language = "python"

            mappings = []
            for event in run_pipeline(
                project_id=project_id,
                repo_url=request and request.repo_url,
                local_path=request and request.local_path,
                language=request_language,
                testbed_name=request_testbed,
                run_fresh=request and request.run_fresh,
                cancel_flags=_cancel_flags,
                github_token=x_github_token,
            ):
                if _cancel_flags.get(project_id) and event["event"] not in ("status", "error"):
                    yield f"data: {json.dumps({'event': 'status', 'data': {'status': 'CANCELLED'}})}\n\n"
                    return
                if event["event"] == "mappings":
                    mappings = event["data"]
                else:
                    yield f"data: {json.dumps(event)}\n\n"

            yield f"data: {json.dumps({'event': 'progress', 'data': 'Storing in Neo4j...'})}\n\n"
            if _cancel_flags.get(project_id):
                yield f"data: {json.dumps({'event': 'status', 'data': {'status': 'CANCELLED'}})}\n\n"
                return

            store = Neo4jStore(neo4j_client=neo4j)
            edge_count = store.store_mappings(mappings, project_id=project_id)
            yield f"data: {json.dumps({'event': 'status', 'data': {'status': 'COMPLETED', 'edges': edge_count}})}\n\n"

        except Exception as e:
            logger.error(f"Instrumentation failed: {e}")
            yield f"data: {json.dumps({'event': 'error', 'data': str(e)})}\n\n"

    return StreamingResponse(run_instrumentation_worker(), media_type="text/event-stream")


@app.post("/projects/{project_id}/instrumentation/cancel")
async def cancel_instrumentation(
    project_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Cancel a running instrumentation process for a project.

    Sets a cancel flag that the SSE worker checks at yield points.
    """
    project = await _resolve_project(project_id, session)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_id and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    _cancel_flags[project_id] = True
    return {"status": "cancelling", "project_id": project_id}


@app.get("/projects/{project_id}/instrumentation/impact")
async def get_instrumentation_impact(
    project_id: int,
    symbols: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    neo4j: Neo4jClient = Depends(get_neo4j)
):
    """
    Get impacted tests based on changed symbols using instrumentation data.

    Query params:
    - symbols: comma-separated list of changed symbol names

    Returns list of impacted tests with confidence scores.
    """
    project = await _resolve_project(project_id, session)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    changed_symbols = [s.strip() for s in symbols.split(",") if s.strip()]

    if not changed_symbols:
        raise HTTPException(status_code=400, detail="No symbols provided")

    from testsquad_core.instrumentation.coverage_transformer import TestSymbolStore

    store = TestSymbolStore(neo4j_client=neo4j)
    impacted = store.get_impacted_tests(project_id=project_id, changed_symbols=changed_symbols)

    return {
        "changed_symbols": changed_symbols,
        "impacted_tests": impacted,
        "count": len(impacted)
    }


@app.post("/projects/{project_id}/instrumentation/impact-from-diff")
async def impact_from_diff(
    project_id: int,
    diff_request: Dict[str, Any],
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Analyze a PR diff against a TestMethodMap to determine impacted E2E tests.

    Body:
        diff: str - PR diff text in unified format
        test_method_map_path: str - Path to TestMethodMap JSON file
        source_root: str - Root path of the source project (for symbol resolution)

    Returns impacted and unimpacted tests with changed symbols.
    """
    project = await _resolve_project(project_id, session)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_id and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized for this project")

    diff_text = diff_request.get("diff", "")
    test_method_map_path = diff_request.get("test_method_map_path", "")
    source_root = diff_request.get("source_root", "")

    if not diff_text:
        raise HTTPException(status_code=400, detail="diff is required")
    if not test_method_map_path:
        raise HTTPException(status_code=400, detail="test_method_map_path is required")
    if not source_root:
        raise HTTPException(status_code=400, detail="source_root is required")
    if not os.path.exists(test_method_map_path):
        raise HTTPException(status_code=400, detail=f"TestMethodMap not found: {test_method_map_path}")
    if not os.path.isdir(source_root):
        raise HTTPException(status_code=400, detail=f"Source root not found: {source_root}")

    try:
        from testsquad_core.instrumentation.diff_parser import DiffParser as FileDiffParser

        result = FileDiffParser.resolve_impacted_tests(
            diff_text=diff_text,
            test_method_map_path=test_method_map_path,
            source_root=source_root,
        )

        return {
            "total_tests": result.total_tests,
            "selected_count": result.selected_count,
            "impacted_tests": [
                {
                    "test_file": t.test_file,
                    "impacted_symbols": t.impacted_symbols,
                    "selected": t.selected,
                }
                for t in result.impacted_tests
            ],
            "unimpacted_tests": [
                {
                    "test_file": t.test_file,
                    "impacted_symbols": t.impacted_symbols,
                    "selected": t.selected,
                }
                for t in result.unimpacted_tests
            ],
            "changed_symbols": result.changed_symbols,
        }
    except Exception as e:
        logger.error(f"Impact from diff failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/projects/{project_id}/style-capsule", response_model=StyleCapsule)
async def update_style_capsule(
    project_id: int,
    capsule_data: Dict[str, Any],
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    proj_result = await session.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if project.owner_id and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized for this project")

    result = await session.execute(
        select(StyleCapsule).where(StyleCapsule.project_id == project_id)
    )
    capsule = result.scalar_one_or_none()

    if capsule:
        for key, value in capsule_data.items():
            if key not in ["id", "project_id"]:
                setattr(capsule, key, value)
    else:
        capsule = StyleCapsule(project_id=project_id, **capsule_data)
        session.add(capsule)

    await session.commit()
    await session.refresh(capsule)
    return capsule

@app.post("/projects/{project_id}/communities/recalculate")
async def recalculate_communities(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    neo4j: Neo4jClient = Depends(get_neo4j)
):
    """
    Independently triggers the Leiden community detection algorithm on the existing graph data.
    Useful for architectural analysis without re-indexing the entire codebase.
    """
    proj_result = await session.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one_or_none()
    
    if project and project.owner_id and project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized for this project")

    async def community_stream():
        try:
            from testsquad_core.analysis.community import CommunityDetector
            yield f"data: {json.dumps({'event': 'log', 'data': '🚀 Initializing Leiden engine for structural analysis...'})}\n\n"
            
            detector = CommunityDetector(neo4j)
            # We run the detection logic
            update_data = detector.detect_communities()
            
            if not update_data:
                yield f"data: {json.dumps({'event': 'log', 'data': '⚠️ No connections found in graph to cluster.'})}\n\n"
                return

            community_count = len(set(d["community_id"] for d in update_data))
            yield f"data: {json.dumps({'event': 'log', 'data': f'🏙️ Found {community_count} neighborhoods. Syncing to Neo4j...'})}\n\n"
            
            # Batch update
            BATCH_SIZE = 500
            total_updated = 0
            for i in range(0, len(update_data), BATCH_SIZE):
                batch = update_data[i:i+BATCH_SIZE]
                result = neo4j.bulk_update_communities(batch)
                if result and result[0].get("updated_count"):
                    total_updated += result[0]["updated_count"]
                yield f"data: {json.dumps({'event': 'reasoning', 'data': f'Updated {total_updated}/{len(update_data)} symbols...'})}\n\n"
            
            yield f"data: {json.dumps({'event': 'log', 'data': '✅ Leiden neighborhoods finalized and projected to the Knowledge Graph.'})}\n\n"
            yield f"data: {json.dumps({'event': 'status', 'data': {'status': 'COMPLETED'}})}\n\n"
        except Exception as e:
            logger.error(f"Community recalculation failed: {e}")
            yield f"data: {json.dumps({'event': 'error', 'data': str(e)})}\n\n"

    return StreamingResponse(community_stream(), media_type="text/event-stream")

@app.post("/projects/{project_id}/sync-style-capsule")
async def sync_style_capsule(
    project_id: int,
    sync_data: Dict[str, Any],
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    g: Github = Depends(get_github_client),
    llm_client: BaseProvider = Depends(get_llm_client)
):
    """Sync style capsule by reading standards from the automation repo."""
    full_repo_name = sync_data.get("full_repo_name")
    provider_name = sync_data.get("provider_name", "Google")
    model_name = sync_data.get("model_name", "gemini-1.5-flash-latest")
    
    if not full_repo_name:
        raise HTTPException(status_code=400, detail="Automation repository name required")

    # Verify access first
    proj_result = await session.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    async def sync_worker():
        try:
            # 1. Fetch Standards file
            repo = g.get_repo(full_repo_name)
            standards_content = ""
            for filename in ["TESTING_STANDARDS.md", "TESTING.md", "README.md"]:
                try:
                    file_content = repo.get_contents(filename)
                    standards_content = file_content.decoded_content.decode()
                    break
                except Exception:
                    continue
            
            if not standards_content:
                logger.warning(f"No testing standards file found in repo {full_repo_name}")
                return

            # 2. Use LLM to extract Style Capsule JSON
            prompt = f"""
            Extract a testing style configuration from the following documentation.
            Return only a JSON object matching this structure:
            {{
                "framework": "pytest" | "playwright" | "jest" | etc.,
                "foundational_patterns": {{ "description": "...", "patterns": [...] }},
                "negative_patterns": ["never do X", ...],
                "reference_examples": [{{ "name": "...", "code": "..." }}]
            }}
            
            DOCUMENTATION:
            {standards_content}
            """
            
            resp = await llm_client.complete(LLMRequest(
                provider_name=provider_name,
                model_name=model_name,
                prompt=prompt
            ))
            
            json_match = re.search(r'```json\n(.*?)\n```', resp.content, re.DOTALL)
            json_str = json_match.group(1) if json_match else resp.content
            extracted_data = json.loads(json_str)

            # 3. Update/Create Capsule (Need a new session for background task)
            from testsquad_shared.persistence.db import SessionLocal
            async with SessionLocal() as bg_session:
                result = await bg_session.execute(
                    select(StyleCapsule).where(StyleCapsule.project_id == project_id)
                )
                capsule = result.scalar_one_or_none()
                
                if not capsule:
                    capsule = StyleCapsule(project_id=project_id)
                    bg_session.add(capsule)
                
                capsule.framework = extracted_data.get("framework", "pytest")
                capsule.foundational_patterns = extracted_data.get("foundational_patterns", {})
                capsule.negative_patterns = extracted_data.get("negative_patterns", [])
                capsule.reference_examples = extracted_data.get("reference_examples", [])
                
                flag_modified(capsule, "foundational_patterns")
                flag_modified(capsule, "negative_patterns")
                flag_modified(capsule, "reference_examples")
                
                await bg_session.commit()
                logger.info(f"Style capsule synced for project {project_id}")

        except Exception as e:
            logger.error(f"Background style sync failed: {e}")

    background_tasks.add_task(sync_worker)
    return {"status": "syncing", "message": "Style extraction started in background."}

@app.get("/api/github/repositories")
async def get_github_repositories(
    current_user: User = Depends(get_current_user),
    g: Github = Depends(get_github_client)
):
    """Proxy endpoint to fetch the user's GitHub repositories."""
    return await list_repositories(g)

@app.get("/api/github/repositories/{owner}/{repo}/pulls")
async def get_github_pull_requests(
    owner: str,
    repo: str,
    current_user: User = Depends(get_current_user),
    g: Github = Depends(get_github_client)
):
    """Proxy endpoint to fetch open PRs for a specific repository."""
    full_name = f"{owner}/{repo}"
    return await list_pull_requests(g, full_name)

@app.get("/api/llm/models")
async def get_llm_models(
    current_user: User = Depends(get_current_user),
    client: BaseProvider = Depends(get_llm_client)
):
    """Fetch available models for the provided (or default) LLM configuration."""
    return await client.list_models()

@app.post("/projects/{project_id}/runs")
async def start_run(
    project_id: int,
    run_data: Dict[str, Any],
    session: AsyncSession = Depends(get_session),
    x_llm_provider: Optional[str] = Header(None),
    x_llm_api_key: Optional[str] = Header(None),
    x_llm_model: Optional[str] = Header(None),
    x_github_token: Optional[str] = Header(None)
):
    """Create a new run record and return the ID, saving LLM config in metadata."""
    # Ensure we capture PR context for targeted analysis
    full_name = run_data.get("full_name")
    pr_number = run_data.get("pr_number")
    
    # Support empty model for Structural-Only mode
    llm_model = run_data.get("llm_model")
    if llm_model is None:
        llm_model = x_llm_model
    
    if not llm_model and llm_model != "":
        llm_model = "gemini-2.5-flash"
    
    run_metadata = {
        "llm_provider": run_data.get("llm_provider") or x_llm_provider or "Google",
        "llm_api_key": run_data.get("llm_api_key") or x_llm_api_key,
        "llm_model": llm_model.strip().strip(","),
        "full_name": full_name,
        "pr_number": pr_number,
        "github_token": x_github_token,
        "automation_repo": run_data.get("automation_repo"),
        "file_paths": run_data.get("file_paths")
    }
    
    run = Run(
        project_id=project_id, 
        commit_sha=run_data.get("commit_sha", "main"),
        status=TaskStatus.PENDING,
        run_metadata=run_metadata
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return {"run_id": run.id}

@app.get("/projects/{project_id}/runs/{run_id}/stream")
async def stream_run(
    project_id: int,
    run_id: int,
    session: AsyncSession = Depends(get_session)
):
    """Stream orchestrator events for a specific run using persisted config."""
    # Fetch the run early to get metadata
    run_result = await session.execute(select(Run).where(Run.id == run_id))
    run = run_result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    metadata = run.run_metadata or {}
    provider_name = metadata.get("llm_provider", "Google")
    api_key = metadata.get("llm_api_key")
    llm_model = metadata.get("llm_model")
    full_name = metadata.get("full_name")
    pr_number = metadata.get("pr_number")
    github_token = metadata.get("github_token")
    automation_repo = metadata.get("automation_repo")
    file_paths_from_meta = metadata.get("file_paths")
    
    # Resolve PR files for targeted analysis if context is available
    pr_files = None
    if full_name and pr_number and not file_paths_from_meta:
        try:
            from .github_service import get_pr_files, Auth
            # Use the token saved during start_run or fallback to system token
            token_to_use = github_token or os.getenv("GITHUB_TOKEN")
            if token_to_use:
                g = Github(auth=Auth.Token(token_to_use))
                pr_files = await get_pr_files(g, full_name, pr_number)
                logger.info(f"Targeting {len(pr_files)} files for PR {pr_number}")
            else:
                logger.warning("No GitHub token available for PR file resolution")
        except Exception as e:
            logger.warning(f"Could not resolve PR files for targeted analysis: {e}")
    
    file_paths = file_paths_from_meta or pr_files

    llm_client = None
    if llm_model:
        llm_client = llm_registry.get_client(provider_name, api_key_override=api_key)
        if not llm_client:
            raise HTTPException(
                status_code=400, 
                detail=f"LLM Provider {provider_name} not configured in run metadata."
            )

    neo4j = Neo4jClient()
    executor = ExecutorClient(base_url=os.getenv("EXECUTOR_URL", "http://executor:8001"))
    orchestrator = RunOrchestrator(neo4j, executor, session, llm_client=llm_client)

    async def event_generator():
        collected_events = []
        try:
            async for event in orchestrator.stream_full_cycle(
                project_id=project_id,
                commit_sha=run.commit_sha,
                max_symbols=10, 
                llm_model=llm_model,
                llm_provider=provider_name,
                file_paths=file_paths,
                automation_repo=automation_repo
            ):
                collected_events.append(event)
                yield f"data: {json.dumps(event)}\n\n"
            
        except Exception as e:
            logger.error(f"Streaming error for run {run_id}: {e}")
            error_event = {'event': 'error', 'data': f"Runtime Error: {str(e)}"}
            collected_events.append(error_event)
            yield f"data: {json.dumps(error_event)}\n\n"
        finally:
            # Final persistence of all collected events using SHIELD
            # This ensures that even if client disconnects, we save the results
            if collected_events:
                await asyncio.shield(persist_final_events(run_id, collected_events))

    async def persist_final_events(rid: int, events: List[Dict]):
        from testsquad_shared.persistence.db import SessionLocal
        try:
            async with SessionLocal() as bg_session:
                res = await bg_session.execute(select(Run).where(Run.id == rid))
                fresh_run = res.scalar_one_or_none()
                if fresh_run:
                    metadata = dict(fresh_run.run_metadata or {})
                    metadata["events"] = events
                    fresh_run.run_metadata = metadata
                    flag_modified(fresh_run, "run_metadata")
                    
                    # Update status if completed/failed event is present
                    if any(e.get("event") == "status" and e.get("data", {}).get("status") == "COMPLETED" for e in events):
                        fresh_run.status = TaskStatus.COMPLETED
                    elif any(e.get("event") == "status" and e.get("data", {}).get("status") == "FAILED" for e in events):
                        fresh_run.status = TaskStatus.FAILED
                    elif any(e.get("event") == "error" for e in events):
                        fresh_run.status = TaskStatus.FAILED
                    
                    await bg_session.commit()
                    logger.info(f"Safely persisted {len(events)} events for run {rid}")
        except Exception as db_err:
            logger.error(f"Critical failure in shielded persistence for run {rid}: {db_err}")

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/projects/{project_id}/runs", response_model=List[Run])
async def get_project_runs(
    project_id: int,
    commit_sha: Optional[str] = None,
    session: AsyncSession = Depends(get_session)
):
    """Fetch run history for a project, optionally filtered by commit."""
    query = select(Run).where(Run.project_id == project_id)
    if commit_sha:
        query = query.where(Run.commit_sha == commit_sha)
    
    result = await session.execute(query.order_by(Run.created_at.desc()))
    return result.scalars().all()

@app.get("/runs/{run_id}/events")
async def get_run_events(
    run_id: int,
    session: AsyncSession = Depends(get_session)
):
    """Retrieve persisted event history for a specific run."""
    result = await session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    return {"events": (run.run_metadata or {}).get("events", [])}
