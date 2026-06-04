"""Tests for POST /projects/{project_id}/analyze-pr — the critical PR impact analysis endpoint."""
import pytest
import sys
import os
import json
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


@pytest.fixture
def mock_neo4j():
    mock = MagicMock()
    mock.query.return_value = []
    return mock


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = "test-user-id"
    return user


@pytest.fixture
def app_with_mocks(mock_neo4j, mock_session, mock_user):
    from testsquad_core.main import app, get_neo4j, get_session, get_current_user
    from testsquad_shared.persistence.models import User, Project

    mock_project = MagicMock(spec=Project)
    mock_project.id = 1
    mock_project.owner_id = mock_user.id

    mock_session.execute = AsyncMock()
    mock_session.scalar_one_or_none = MagicMock(return_value=mock_project)

    async def mock_get_session():
        result = AsyncMock()
        result.scalar_one_or_none = MagicMock(return_value=mock_project)
        mock_session.execute.return_value = result
        yield mock_session

    old_neo4j = app.dependency_overrides.get(get_neo4j)
    old_session = app.dependency_overrides.get(get_session)
    old_user = app.dependency_overrides.get(get_current_user)

    app.dependency_overrides[get_neo4j] = lambda: mock_neo4j
    app.dependency_overrides[get_session] = mock_get_session
    app.dependency_overrides[get_current_user] = lambda: mock_user

    yield app

    if old_neo4j:
        app.dependency_overrides[get_neo4j] = old_neo4j
    else:
        app.dependency_overrides.pop(get_neo4j, None)
    if old_session:
        app.dependency_overrides[get_session] = old_session
    else:
        app.dependency_overrides.pop(get_session, None)
    if old_user:
        app.dependency_overrides[get_current_user] = old_user
    else:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def valid_pr_data():
    return {
        "full_name": "hbahuguna/Test-Radius",
        "pr_number": 14,
        "commit_sha": "1648a253401504e0d0e0f15976b21e03a1ae6528",
        "file_paths": ["artifacts/testradius/src/pages/Home.tsx"],
    }


class TestAnalyzePR:
    """Test POST /projects/{project_id}/analyze-pr endpoint."""

    # --- Happy path ---

    def test_analyze_pr_returns_correct_structure(self, app_with_mocks, mock_neo4j, mock_session, valid_pr_data):
        """Valid PR data returns 200 with expected response keys."""

        mock_neo4j.query.side_effect = [
            # ingestor query result
            [
                {"name": "HomePage", "file_path": "Home.tsx", "pri": 5200.0,
                 "summary": "Home page component", "type": "component", "start": 4, "end": 527},
            ],
            # store_mappings query result
            [],
            # evidence edges query
            [
                {"test_name": "home.spec", "test_file": "artifacts/e2e-tests/tests/home.spec.ts"},
                {"test_name": "Home.test", "test_file": "artifacts/testradius/src/pages/Home.test.tsx"},
            ],
        ]

        from fastapi.testclient import TestClient
        client = TestClient(app_with_mocks)
        response = client.post(
            "/projects/1/analyze-pr",
            json=valid_pr_data,
            headers={"Authorization": "Bearer test-token"},
        )

        print(f"Response status: {response.status_code}")
        print(f"Response body: {response.json()}")

        assert response.status_code == 200
        body = response.json()
        assert "results" in body
        assert "symbols_selected" in body
        assert "total_tests_reused" in body
        assert "pr_files_analyzed" in body
        assert body["pr_files_analyzed"] == 1
        assert body["symbols_selected"] >= 1

    def test_analyze_pr_finds_existing_tests(self, app_with_mocks, mock_neo4j, mock_session, valid_pr_data):
        """Symbols with evidence edges return matching tests."""

        mock_neo4j.query.side_effect = [
            [
                {"name": "HomePage", "file_path": "Home.tsx", "pri": 5200.0,
                 "summary": "Home page component", "type": "component", "start": 4, "end": 527},
            ],
            [],
            [
                {"test_name": "home.spec", "test_file": "artifacts/e2e-tests/tests/home.spec.ts"},
            ],
        ]

        from fastapi.testclient import TestClient
        client = TestClient(app_with_mocks)
        response = client.post(
            "/projects/1/analyze-pr",
            json=valid_pr_data,
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total_tests_reused"] >= 1
        assert len(body["results"]) >= 1
        symbol = body["results"][0]
        assert "existing_tests" in symbol
        assert len(symbol["existing_tests"]) >= 1

    # --- Error cases ---

    def test_analyze_pr_missing_full_name(self, app_with_mocks, mock_neo4j, mock_session):
        """Missing full_name returns 400."""

        from fastapi.testclient import TestClient
        client = TestClient(app_with_mocks)
        response = client.post(
            "/projects/1/analyze-pr",
            json={"pr_number": 14},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 400

    def test_analyze_pr_missing_pr_number(self, app_with_mocks, mock_neo4j, mock_session):
        """Missing pr_number returns 400."""

        from fastapi.testclient import TestClient
        client = TestClient(app_with_mocks)
        response = client.post(
            "/projects/1/analyze-pr",
            json={"full_name": "hbahuguna/Test-Radius"},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 400

    def test_analyze_pr_project_not_found(self, app_with_mocks, mock_neo4j, mock_session, valid_pr_data):
        """Non-existent project returns 404."""

        mock_session.execute = AsyncMock()
        mock_session.execute.return_value = AsyncMock(scalar_one_or_none=MagicMock(return_value=None))

        from fastapi.testclient import TestClient
        client = TestClient(app_with_mocks)
        response = client.post(
            "/projects/999/analyze-pr",
            json=valid_pr_data,
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 404

    # --- Edge cases ---

    def test_analyze_pr_no_file_changes(self, app_with_mocks, mock_neo4j, mock_session):
        """PR with zero file changes returns empty results."""

        mock_neo4j.query.side_effect = [[], [], []]

        from fastapi.testclient import TestClient
        client = TestClient(app_with_mocks)
        response = client.post(
            "/projects/1/analyze-pr",
            json={
                "full_name": "hbahuguna/Test-Radius",
                "pr_number": 14,
                "file_paths": [],
            },
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["symbols_selected"] == 0
        assert body["total_tests_reused"] == 0
        assert body["pr_files_analyzed"] == 0

    def test_analyze_pr_symbols_without_tests(self, app_with_mocks, mock_neo4j, mock_session, valid_pr_data):
        """Symbols exist but no evidence edges — returns symbols, zero tests."""

        mock_neo4j.query.side_effect = [
            [
                {"name": "SomeSymbol", "file_path": "utils.ts", "pri": 100.0,
                 "summary": "Utility", "type": "function", "start": 1, "end": 10},
            ],
            [],
            [],  # No evidence edges
        ]

        from fastapi.testclient import TestClient
        client = TestClient(app_with_mocks)
        response = client.post(
            "/projects/1/analyze-pr",
            json=valid_pr_data,
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["symbols_selected"] >= 1
        assert body["total_tests_reused"] == 0

    def test_analyze_pr_limits_to_ten_symbols(self, app_with_mocks, mock_neo4j, mock_session, valid_pr_data):
        """More than 10 matching symbols should be capped at 10."""

        symbols = []
        for i in range(20):
            symbols.append({
                "name": f"Symbol{i}", "file_path": f"file{i}.ts",
                "pri": float(100 - i), "summary": f"Summary {i}",
                "type": "function", "start": i, "end": i + 1,
            })
        mock_neo4j.query.side_effect = [
            symbols,
            [],
            [],  # No evidence edges for any
        ]

        from fastapi.testclient import TestClient
        client = TestClient(app_with_mocks)
        response = client.post(
            "/projects/1/analyze-pr",
            json=valid_pr_data,
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["symbols_selected"] <= 10

    def test_analyze_pr_combines_both_query_results(self, app_with_mocks, mock_neo4j, mock_session, valid_pr_data):
        """Results from both ingestor and store_mappings queries are combined."""

        mock_neo4j.query.side_effect = [
            [{"name": "SymbolA", "file_path": "a.ts", "pri": 5000.0,
              "summary": "A", "type": "function", "start": 1, "end": 5}],
            [{"name": "SymbolB", "file_path": "b.ts", "pri": 6000.0,
              "summary": "B", "type": "class", "start": 1, "end": 10}],
            [{"test_name": "test_a", "test_file": "a.test.ts"}],
            [{"test_name": "test_b", "test_file": "b.test.ts"}],
        ]

        from fastapi.testclient import TestClient
        client = TestClient(app_with_mocks)
        response = client.post(
            "/projects/1/analyze-pr",
            json=valid_pr_data,
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["symbols_selected"] >= 2
