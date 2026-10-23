import time

import pytest
from fastapi.testclient import TestClient

from cell.config import Settings
from cell.main import create_app
from cell.models import DependencyStatus


class StubProbe:
    def __init__(self, statuses: dict[str, DependencyStatus] | None = None) -> None:
        self.statuses = statuses or {}

    async def probe(self, url: str | None) -> DependencyStatus:
        if url is None:
            return DependencyStatus.NOT_CONFIGURED
        return self.statuses.get(url, DependencyStatus.UNREACHABLE)


def make_client(
    probe: StubProbe,
    *,
    aut_url: str | None = None,
    graph_url: str | None = None,
) -> TestClient:
    settings = Settings(
        aut_health_url=aut_url,
        graph_health_url=graph_url,
        probe_timeout_seconds=0.1,
    )
    return TestClient(create_app(settings=settings, probe=probe))


def test_unconfigured_dependencies_are_ready() -> None:
    client = make_client(StubProbe())
    response = client.get("/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["aut_status"] == "not_configured"
    assert body["graph_status"] == "not_configured"


def test_unreachable_aut_blocks_readiness() -> None:
    aut = "http://aut.test/health"
    client = make_client(
        StubProbe({aut: DependencyStatus.UNREACHABLE}),
        aut_url=aut,
    )

    response = client.get("/v1/health")

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["aut_status"] == "unreachable"
    assert body["graph_status"] == "not_configured"


@pytest.mark.parametrize(
    "status",
    [DependencyStatus.DEGRADED, DependencyStatus.UNREACHABLE],
)
def test_unhealthy_graph_blocks_readiness(status: DependencyStatus) -> None:
    graph = "http://graph.test"
    client = make_client(StubProbe({graph: status}), graph_url=graph)

    response = client.get("/v1/health")

    assert response.status_code == 503
    assert response.json()["graph_status"] == status.value


def test_healthy_dependencies_are_ready() -> None:
    aut = "http://aut.test/health"
    graph = "http://graph.test"
    client = make_client(
        StubProbe({aut: DependencyStatus.OK, graph: DependencyStatus.OK}),
        aut_url=aut,
        graph_url=graph,
    )

    response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "ready": True,
        "aut_status": "ok",
        "graph_status": "ok",
        "version": "0.1.0",
    }


def test_health_does_not_leak_secrets_or_paths() -> None:
    client = make_client(StubProbe())

    body = client.get("/v1/health").text

    assert set(client.get("/v1/health").json()) == {
        "ready",
        "aut_status",
        "graph_status",
        "version",
    }
    assert "dev-only-change-me" not in body
    assert "/workspace" not in body


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_documentation_routes_are_disabled(path: str) -> None:
    client = make_client(StubProbe())

    assert client.get(path).status_code == 404


def test_root_is_not_a_landing_page() -> None:
    client = make_client(StubProbe())

    assert client.get("/").status_code == 404


def test_health_endpoint_is_cheap() -> None:
    """E1-S2 AC2: p95 < 50 ms with a healthy (stubbed) probe."""

    client = make_client(StubProbe())
    samples: list[float] = []

    for _ in range(100):
        started = time.perf_counter()
        assert client.get("/v1/health").status_code == 200
        samples.append((time.perf_counter() - started) * 1000)

    samples.sort()
    p95 = samples[int(len(samples) * 0.95) - 1]

    assert p95 < 50, f"p95 was {p95:.1f} ms"
