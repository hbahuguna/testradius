import pytest
import json
from unittest.mock import patch
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from testsquad_core.main import app
from testsquad_shared.persistence.models import Project
from testsquad_core.persistence.run_models import Run

@pytest.mark.asyncio
async def test_run_events_persistence(session: AsyncSession):
    # 1. Setup - Create a project and a run
    project = Project(name="Test Project Persistence")
    session.add(project)
    await session.commit()
    await session.refresh(project)
    
    run = Run(project_id=project.id, commit_sha="test_sha_123", status="PENDING", run_metadata={})
    session.add(run)
    await session.commit()
    await session.refresh(run)
    
    # 2. Mock Orchestrator to yield mock events
    mock_events = [
        {"event": "reasoning", "data": "Starting test reasoning..."},
        {"event": "status", "data": {"run_id": run.id, "status": "RUNNING"}},
        {"event": "status", "data": {"run_id": run.id, "status": "COMPLETED"}}
    ]
    
    async def mock_stream(*args, **kwargs):
        # We need to yield events one by one to simulate the orchestrator
        for ev in mock_events:
            yield ev
            
    # We patch the stream_full_cycle in Orchestrator
    with patch("testsquad_core.orchestration.run_orchestrator.RunOrchestrator.stream_full_cycle", side_effect=mock_stream):
        # 3. Call the streaming endpoint using AsyncClient
        async with AsyncClient(app=app, base_url="http://test") as ac:
            # We must set a realistic header and potentially auth if required
            # But here get_session is overridden in conftest.py
            response = await ac.get(f"/projects/{project.id}/runs/{run.id}/stream")
            assert response.status_code == 200
            
            # Consume the stream
            lines = []
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    lines.append(json.loads(line[6:]))
            
            assert len(lines) == 3

    # 4. Verify Persistence in DB
    # We need to expire the object or fetch fresh to see changes from the background generator
    # Actually, the same session is used (if it works correctly with dependency overrides)
    result = await session.execute(select(Run).where(Run.id == run.id))
    # We use scalar_one() and refresh
    persisted_run = result.scalar_one()
    await session.refresh(persisted_run)
    
    events = persisted_run.run_metadata.get("events", [])
    
    # Assertions
    assert len(events) == 3, f"Expected 3 events, got {len(events)}. Metadata: {persisted_run.run_metadata}"
    assert events[0]["event"] == "reasoning"
    assert events[2]["data"]["status"] == "COMPLETED"
