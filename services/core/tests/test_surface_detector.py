import pytest
from unittest.mock import MagicMock, patch
from testsquad_core.analysis.surface import SurfaceDetector

def test_decorator_detection():
    mock_neo4j = MagicMock()
    detector = SurfaceDetector(mock_neo4j)
    
    # Mock Neo4j query for decorated symbols
    mock_neo4j.query.return_value = [
        {"name": "get_user", "file_path": "api.py", "decorators": ["@app.get('/user')"]},
        {"name": "internal_helper", "file_path": "api.py", "decorators": ["@lru_cache"]}
    ]
    
    detector._detect_via_decorators(project_id=1)
    
    # Should only tag the one with the API marker
    mock_neo4j.tag_symbol_as_entry_point.assert_called_once_with(
        "api.py", "get_user", "api"
    )

def test_file_heuristic_detection():
    mock_neo4j = MagicMock()
    detector = SurfaceDetector(mock_neo4j)
    
    # Mock Neo4j query for symbols in cli.py
    mock_neo4j.query.side_effect = [
        [{"name": "main", "file_path": "cli.py"}], # for main.py
        [], # for app.py
        [{"name": "run", "file_path": "src/cli.py"}], # for cli.py
        [], # for wsgi.py
        [], # for asgi.py
        []  # for __init__.py
    ]
    
    detector._detect_via_file_heuristics(project_id=1)
    
    # Should tag symbols in cli-related files
    assert mock_neo4j.tag_symbol_as_entry_point.call_count == 2

def test_orphan_analysis_detection():
    mock_neo4j = MagicMock()
    detector = SurfaceDetector(mock_neo4j)
    
    # Mock Neo4j query for orphans
    mock_neo4j.query.return_value = [
        {"name": "public_api", "file_path": "service.py"}
    ]
    
    detector._detect_via_orphan_analysis(project_id=1)
    
    mock_neo4j.tag_symbol_as_entry_point.assert_called_once_with(
        "service.py", "public_api", "orphan"
    )
