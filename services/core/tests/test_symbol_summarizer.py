import pytest
import asyncio
from unittest.mock import MagicMock, patch, mock_open, AsyncMock
from testsquad_core.intelligence.summarizer import SymbolSummarizer
from testsquad_shared.models import LLMResponse

@pytest.mark.anyio
async def test_symbol_summarizer_batch_processing():
    mock_neo4j = MagicMock()
    summarizer = SymbolSummarizer(mock_neo4j)
    
    # Mock LLM Client
    mock_client = MagicMock()
    mock_client.complete = AsyncMock()
    
    # Setup mock response
    mock_response = LLMResponse(
        content='[{"name": "test_func", "file": "test.py", "summary": "A test function that does nothing."}]',
        model_name="gemini-1.5-flash",
        provider_name="Google",
        token_usage={}
    )
    
    # Mock registry and provider
    with patch("testsquad_core.intelligence.registry.llm_registry.get_client") as mock_get_client, \
         patch.object(summarizer, "_get_symbol_content", return_value="def test_func(): pass"):
        
        mock_get_client.return_value = mock_client
        mock_client.complete.return_value = mock_response
        
        batch = [{
            "name": "test_func",
            "file_path": "test.py",
            "start_line": 1,
            "end_line": 2
        }]
        
        await summarizer._summarize_batch(batch)
        
        # Verify Neo4j update
        mock_neo4j.update_symbol_summary.assert_called_once_with(
            "test.py", "test_func", "A test function that does nothing."
        )

@pytest.mark.anyio
async def test_summarize_all_missing_orchestration():
    mock_neo4j = MagicMock()
    summarizer = SymbolSummarizer(mock_neo4j)
    
    # Mock Neo4j query for missing symbols
    mock_neo4j.query.return_value = [
        {"name": "func1", "file_path": "f1.py", "start_line": 1, "end_line": 5},
        {"name": "func2", "file_path": "f2.py", "start_line": 10, "end_line": 15}
    ]
    
    with patch.object(summarizer, "_summarize_batch") as mock_summarize_batch:
        mock_summarize_batch.return_value = asyncio.Future()
        mock_summarize_batch.return_value.set_result(None)
        
        await summarizer.summarize_all_missing(project_id=1)
        
        # Verify query was called
        assert mock_neo4j.query.called
        # Verify batch processing was called
        mock_summarize_batch.assert_called_once()
        assert len(mock_summarize_batch.call_args[0][0]) == 2
