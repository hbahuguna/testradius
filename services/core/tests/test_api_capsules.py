import pytest
from httpx import AsyncClient
from testsquad_core.main import app
from testsquad_shared.persistence.models import StyleCapsule

@pytest.mark.asyncio
async def test_get_style_capsule_not_found():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/projects/999/style-capsule")
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_update_create_style_capsule(session):
    # Note: 'session' fixture should provide a clean DB session
    # For now, we test the logic via the app
    async with AsyncClient(app=app, base_url="http://test") as ac:
        # 1. Create
        data = {
            "framework": "pytest",
            "foundational_patterns": {"indent": 4},
            "negative_patterns": ["no_print"],
            "reference_examples": [{"name": "ex1", "code": "pass"}]
        }
        response = await ac.put("/projects/1/style-capsule", json=data)
        assert response.status_code == 200
        assert response.json()["framework"] == "pytest"
        
        # 2. Get
        response = await ac.get("/projects/1/style-capsule")
        assert response.status_code == 200
        assert response.json()["foundational_patterns"] == {"indent": 4}
        
        # 3. Update
        update_data = {"framework": "unittest"}
        response = await ac.put("/projects/1/style-capsule", json=update_data)
        assert response.status_code == 200
        assert response.json()["framework"] == "unittest"
        # Verify other fields persist
        assert response.json()["negative_patterns"] == ["no_print"]
