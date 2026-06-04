import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from testsquad_core.orchestration.run_orchestrator import RunOrchestrator
from testsquad_shared.persistence.models import StyleCapsule
from testsquad_shared.models import LLMRequest, LLMResponse

@pytest.mark.asyncio
async def test_orchestrator_style_injection():
    # Mock Neo4j
    mock_neo4j = MagicMock()
    mock_neo4j.query.return_value = []
    
    # Mock Executor
    mock_executor = AsyncMock()
    
    async def mock_stream_logs(run_id):
        if False: yield # Make it an async generator
        return

    mock_executor.stream_logs = MagicMock(side_effect=mock_stream_logs)
    
    # Mock Session
    mock_session = AsyncMock()
    
    # Mock Capsule
    mock_capsule = StyleCapsule(
        project_id=1,
        framework="pytest",
        foundational_patterns={"test": "pattern"},
        negative_patterns=["NO_BANANAS"],
        reference_examples=[{"name": "ref", "code": "print('hello')"}]
    )
    
    # Mock query result
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_capsule
    mock_session.execute.return_value = mock_result
    
    orchestrator = RunOrchestrator(mock_neo4j, mock_executor, mock_session)
    
    # Mock LLM Client
    mock_llm = AsyncMock()
    mock_llm.complete.return_value = LLMResponse(
        content="```python\ndef test_dummy(): pass\n```",
        model_name="test",
        provider_name="test"
    )
    
    with patch("testsquad_core.orchestration.run_orchestrator.llm_registry.get_client", return_value=mock_llm):
        with patch.object(orchestrator, "_get_code_snippet", return_value="def dummy(): pass"):
            with patch.object(orchestrator, "_extract_code", return_value="def test_dummy(): pass"):
                # We don't need to run the whole thing, just _process_symbol
                await orchestrator._process_symbol(
                    project_id=1,
                    run_id=1,
                    symbol={"name": "dummy", "file_path": "test.py", "start": 1, "end": 2},
                    commit_sha="abc"
                )
                
                # Verify LLM call
                args, _ = mock_llm.complete.call_args
                request = args[0]
                assert isinstance(request, LLMRequest)
                assert "STYLE CAPSULE:" in request.prompt
                assert "NO_BANANAS" in request.prompt
                assert "print('hello')" in request.prompt
