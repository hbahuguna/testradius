import pytest
from unittest.mock import MagicMock, patch
from testsquad_core.graph.client import Neo4jClient

@pytest.fixture
def mock_driver():
    with patch("neo4j.GraphDatabase.driver") as mock:
        yield mock

def test_neo4j_client_query(mock_driver):
    client = Neo4jClient(uri="bolt://localhost:7687", user="test", password="test_password")
    mock_session = MagicMock()
    mock_driver.return_value.session.return_value.__enter__.return_value = mock_session
    
    # Mocking result
    mock_result = [MagicMock()]
    mock_result[0].data.return_value = {"n": "node"}
    mock_session.run.return_value = mock_result
    
    res = client.query("MATCH (n) RETURN n")
    assert res == [{"n": "node"}]
    assert mock_session.run.called

def test_sync_project_cypher(mock_driver):
    client = Neo4jClient()
    mock_session = MagicMock()
    mock_driver.return_value.session.return_value.__enter__.return_value = mock_session
    
    client.sync_project(1, "TestProject")
    
    assert mock_session.run.called
    args, kwargs = mock_session.run.call_args
    cypher = args[0]
    params = args[1]
    
    assert "MERGE (p:Project {sql_id: $project_id})" in cypher
    assert params["project_id"] == 1
    assert params["name"] == "TestProject"
