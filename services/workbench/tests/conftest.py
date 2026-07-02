import pytest
from httpx import AsyncClient, ASGITransport

from testsquad_workbench.main import app


@pytest.fixture
def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")
