"""End-to-end pipeline integration tests — full GitHub webhook → TIA → execute → comment flow."""
import pytest
import sys
import os
import json
from unittest.mock import MagicMock, AsyncMock, patch, ANY

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestPipelineIntegration:
    """Verify the full pipeline produces responses the GitHub App can consume."""

    @pytest.fixture
    def mock_neo4j(self):
        mock = MagicMock()
        return mock

    @pytest.fixture
    def mock_session(self):
        return AsyncMock()

    @pytest.fixture
    def mock_user(self):
        user = MagicMock()
        user.id = "test-user-id"
        return user

    @pytest.fixture
    def app_with_mocks(self, mock_neo4j, mock_session, mock_user):
        from testsquad_core.main import app, get_neo4j, get_session, get_current_user
        from testsquad_shared.persistence.models import Project

        mock_project = MagicMock(spec=Project)
        mock_project.id = 1
        mock_project.owner_id = mock_user.id

        async def mock_get_session():
            result = AsyncMock()
            result.scalar_one_or_none = MagicMock(return_value=mock_project)
            mock_session.execute = AsyncMock(return_value=result)
            yield mock_session

        old_neo4j = app.dependency_overrides.get(get_neo4j)
        old_session = app.dependency_overrides.get(get_session)
        old_user = app.dependency_overrides.get(get_current_user)

        app.dependency_overrides[get_neo4j] = lambda: mock_neo4j
        app.dependency_overrides[get_session] = mock_get_session
        app.dependency_overrides[get_current_user] = lambda: mock_user

        yield mock_neo4j, app

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

    # --- Full flow: analyze-pr → execute-tests ---

    def test_happy_path_returns_consumable_results(self, app_with_mocks):
        """Full flow produces results the GitHub App can format and post."""

        mock_neo4j, app = app_with_mocks

        mock_neo4j.query.side_effect = [
            # analyze-pr: ingestor query
            [{"name": "HomePage", "file_path": "Home.tsx", "pri": 5200.0,
              "summary": "Home page", "type": "component", "start": 4, "end": 527}],
            # analyze-pr: store_mappings query
            [],
            # analyze-pr: evidence edges
            [{"test_name": "home.spec", "test_file": "artifacts/e2e-tests/tests/home.spec.ts"},
             {"test_name": "Home.test", "test_file": "artifacts/testradius/src/pages/Home.test.tsx"}],
        ]

        from fastapi.testclient import TestClient
        client = TestClient(app)

        # Step 1: analyze-pr
        tia_response = client.post(
            "/projects/1/analyze-pr",
            json={
                "full_name": "hbahuguna/Test-Radius",
                "pr_number": 14,
                "commit_sha": "abc123",
                "file_paths": ["Home.tsx"],
            },
            headers={"Authorization": "Bearer test-token"},
        )

        assert tia_response.status_code == 200
        tia = tia_response.json()

        # Verify TIA response is consumable by GitHub App
        assert "results" in tia
        assert "symbols_selected" in tia
        assert "total_tests_reused" in tia
        assert isinstance(tia["results"], list)

        # Extract tests for execution
        tests_to_run = []
        for symbol in tia["results"]:
            for test in symbol.get("existing_tests", []):
                tests_to_run.append({
                    "name": test["test_name"],
                    "file": test["test_file"],
                })

        assert len(tests_to_run) >= 1, "TIA should find at least one test"

    @patch("testsquad_core.main.run_tests")
    def test_full_pipeline_mocked(self, mock_run_tests, app_with_mocks):
        """Full pipeline: analyze-pr output feeds directly into execute-tests input."""

        mock_neo4j, app = app_with_mocks

        mock_neo4j.query.side_effect = [
            [{"name": "HomePage", "file_path": "Home.tsx", "pri": 5200.0,
              "summary": "Home page", "type": "component", "start": 4, "end": 527}],
            [],
            [{"test_name": "home.spec", "test_file": "artifacts/e2e-tests/tests/home.spec.ts"}],
        ]

        mock_run_tests.return_value = {
            "status": "completed",
            "total": 1,
            "passed": 1,
            "failed": 0,
            "results": [{"name": "t", "file": "f.ts", "status": "passed", "duration": "0.1s", "error": ""}],
        }

        from fastapi.testclient import TestClient
        client = TestClient(app)

        tia_response = client.post(
            "/projects/1/analyze-pr",
            json={"full_name": "hbahuguna/Test-Radius", "pr_number": 14, "file_paths": ["Home.tsx"]},
            headers={"Authorization": "Bearer test-token"},
        )
        assert tia_response.status_code == 200

        tia = tia_response.json()
        tests_to_run = []
        for symbol in tia["results"]:
            for test in symbol.get("existing_tests", []):
                tests_to_run.append({"name": test["test_name"], "file": test["test_file"]})

        assert len(tests_to_run) == 1

        exec_response = client.post(
            "/projects/1/execute-tests",
            json={
                "owner": "hbahuguna", "repo": "Test-Radius", "pr_number": 14,
                "commit_sha": "abc123", "github_token": "ghs_token",
                "tests": tests_to_run,
            },
            headers={"Authorization": "Bearer test-token"},
        )

        assert exec_response.status_code == 200
        exec_data = exec_response.json()
        assert exec_data["status"] == "completed"
        assert exec_data["passed"] >= 1
        mock_run_tests.assert_called_once()

    # --- analyze-pr + execute-tests response format validation ---

    def test_analyze_pr_response_has_correct_keys(self, app_with_mocks):
        """analyze-pr response has all keys the GitHub App expects."""

        mock_neo4j, app = app_with_mocks
        mock_neo4j.query.side_effect = [[], [], []]

        from fastapi.testclient import TestClient
        client = TestClient(app)
        response = client.post(
            "/projects/1/analyze-pr",
            json={"full_name": "hbahuguna/Test-Radius", "pr_number": 14, "file_paths": []},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        body = response.json()

        required_keys = {"project_id", "full_name", "pr_number", "commit_sha",
                         "pr_files_analyzed", "symbols_selected", "tests_selected",
                         "total_tests_reused", "results"}
        assert required_keys.issubset(set(body.keys())), f"Missing keys: {required_keys - set(body.keys())}"

    @patch("testsquad_core.main.run_tests")
    def test_execute_tests_response_has_correct_keys(self, mock_run_tests, app_with_mocks):
        """execute-tests response has all keys the GitHub App expects."""

        mock_neo4j, app = app_with_mocks
        mock_run_tests.return_value = {
            "status": "completed", "total": 1, "passed": 1, "failed": 0,
            "results": [{"name": "t", "file": "f.ts", "status": "passed", "duration": "0.1s", "error": ""}],
        }

        from fastapi.testclient import TestClient
        client = TestClient(app)
        response = client.post(
            "/projects/1/execute-tests",
            json={
                "owner": "hbahuguna", "repo": "Test-Radius", "pr_number": 14,
                "github_token": "ghs_token", "tests": [{"name": "t", "file": "f.ts"}],
            },
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        body = response.json()

        required_keys = {"project_id", "full_name", "pr_number", "commit_sha",
                         "status", "total", "passed", "failed", "results"}
        assert required_keys.issubset(set(body.keys())), f"Missing keys: {required_keys - set(body.keys())}"

        for result in body["results"]:
            assert "name" in result
            assert "file" in result
            assert "status" in result
            assert result["status"] in ("passed", "failed", "unknown")

    # --- Edge case: no impacted tests ---

    def test_analyze_pr_no_impacted_tests(self, app_with_mocks):
        """When no tests are impacted, response should be empty but valid."""

        mock_neo4j, app = app_with_mocks
        mock_neo4j.query.side_effect = [[], [], []]

        from fastapi.testclient import TestClient
        client = TestClient(app)
        response = client.post(
            "/projects/1/analyze-pr",
            json={"full_name": "hbahuguna/Test-Radius", "pr_number": 14, "file_paths": ["unmapped.ts"]},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total_tests_reused"] == 0
        assert body["results"] == []

    # --- GitHub App comment format validation ---

    def test_tia_results_can_build_comment_table(self, app_with_mocks):
        """TIA results can be formatted into a markdown comment table."""

        mock_neo4j, app = app_with_mocks
        mock_neo4j.query.side_effect = [
            [{"name": "HomePage", "file_path": "Home.tsx", "pri": 5200.0,
              "summary": "Home page", "type": "component", "start": 4, "end": 527}],
            [],
            [{"test_name": "home.spec", "test_file": "artifacts/e2e-tests/tests/home.spec.ts"}],
        ]

        from fastapi.testclient import TestClient
        client = TestClient(app)
        response = client.post(
            "/projects/1/analyze-pr",
            json={"full_name": "hbahuguna/Test-Radius", "pr_number": 14, "file_paths": ["Home.tsx"]},
            headers={"Authorization": "Bearer test-token"},
        )

        tia = response.json()

        # Simulate GitHub App comment building
        lines = ["## TestRadius - Test Impact Analysis",
                 f"**PR:** `{tia['full_name']}`",
                 f"**Files changed:** {tia['pr_files_analyzed']}",
                 f"**Symbols analyzed:** {tia['symbols_selected']}",
                 f"**Tests selected:** {tia['total_tests_reused']}",
                 "",
                 "| Test | File | Impacted Symbol |",
                 "|------|------|-----------------|"]

        for sym in tia["results"]:
            for test in sym.get("existing_tests", []):
                lines.append(f"| {test['test_name']} | {test['test_file']} | {sym['symbol_name']} |")

        comment = "\n".join(lines)
        assert "TestRadius" in comment
        assert "home.spec" in comment
        assert "HomePage" in comment
