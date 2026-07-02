import pytest
from httpx import AsyncClient, ASGITransport

from testsquad_workbench.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestAnalyzeEndpoint:
    async def test_analyze_local_file(self, client):
        html_path = "/tmp/test-page.html"
        response = await client.post(
            "/analyze",
            json={"url": f"file://{html_path}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["url"].endswith("test-page.html")
        assert data["title"] == "Login Page"
        assert data["element_count"] > 0
        assert data["root"]["tag"] == "body"

    async def test_analyze_missing_file(self, client):
        response = await client.post(
            "/analyze",
            json={"url": "file:///tmp/nonexistent.html"},
        )
        assert response.status_code == 400

    async def test_analyze_invalid_url(self, client):
        response = await client.post(
            "/analyze",
            json={"url": "not-a-url"},
        )
        assert response.status_code == 400

    async def test_analyze_missing_body(self, client):
        response = await client.post(
            "/analyze",
            json={},
        )
        assert response.status_code == 422


class TestComGenEndpoint:
    async def test_com_gen_local_file(self, client):
        response = await client.post(
            "/com-gen",
            json={
                "url": "file:///tmp/test-page.html",
                "selector": "form#login",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["component_type"] == "LoginForm"
        assert "class LoginForm" in data["python_code"]
        assert data["confidence"] > 0

    async def test_com_gen_bad_selector(self, client):
        response = await client.post(
            "/com-gen",
            json={
                "url": "file:///tmp/test-page.html",
                "selector": "div.nonexistent",
            },
        )
        assert response.status_code == 404

    async def test_com_gen_missing_selector(self, client):
        response = await client.post(
            "/com-gen",
            json={"url": "file:///tmp/test-page.html"},
        )
        assert response.status_code == 422


class TestComponentsEndpoint:
    async def test_components_local_file(self, client):
        response = await client.post(
            "/components",
            json={"url": "file:///tmp/test-page.html"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["url"].endswith("test-page.html")
        types = [c["component_type"] for c in data["components"]]
        assert "NavBar" in types
        assert "LoginForm" in types
        for c in data["components"]:
            assert "selector" in c
            assert "tag" in c
            assert c["confidence"] > 0

    async def test_components_missing_file(self, client):
        response = await client.post(
            "/components",
            json={"url": "file:///tmp/nonexistent.html"},
        )
        assert response.status_code == 400


class TestPomGenEndpoint:
    async def test_pom_gen_basic(self, client):
        response = await client.post(
            "/pom-gen",
            json={
                "url": "file:///tmp/test-page.html",
                "selectors": ["nav", "form#login"],
                "suite_name": "LoginSuite",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["suite_name"] == "LoginSuite"
        filenames = [f["filename"] for f in data["files"]]
        assert "LoginSuite.py" in filenames
        assert "test_LoginSuite.py" in filenames
        assert "LoginForm.py" in filenames or "NavBar.py" in filenames
        for f in data["files"]:
            assert len(f["content"]) > 0
            assert f["type"] in ("pom", "test", "com")

    async def test_pom_gen_empty_selectors(self, client):
        response = await client.post(
            "/pom-gen",
            json={
                "url": "file:///tmp/test-page.html",
                "selectors": [],
            },
        )
        assert response.status_code == 400

    async def test_pom_gen_nonexistent_selector(self, client):
        response = await client.post(
            "/pom-gen",
            json={
                "url": "file:///tmp/test-page.html",
                "selectors": ["div.nonexistent"],
            },
        )
        assert response.status_code == 400

    async def test_pom_gen_valid_python(self, client):
        import ast
        response = await client.post(
            "/pom-gen",
            json={
                "url": "file:///tmp/test-page.html",
                "selectors": ["form#login"],
                "suite_name": "LoginSuite",
            },
        )
        assert response.status_code == 200
        for f in response.json()["files"]:
            ast.parse(f["content"])
