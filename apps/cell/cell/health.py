import asyncio
from typing import Protocol

import httpx

from .models import DependencyStatus


class DependencyProbe(Protocol):
    async def probe(self, url: str | None) -> DependencyStatus: ...


class HttpProbe:
    """Minimal readiness probe: any HTTP response below 500 is healthy."""

    def __init__(self, timeout_seconds: float = 1.0) -> None:
        self._timeout = timeout_seconds

    async def probe(self, url: str | None) -> DependencyStatus:
        if not url:
            return DependencyStatus.NOT_CONFIGURED
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url)
        except httpx.HTTPError:
            return DependencyStatus.UNREACHABLE
        if response.status_code < 500:
            return DependencyStatus.OK
        return DependencyStatus.DEGRADED


async def probe_dependencies(
    probe: DependencyProbe, aut_url: str | None, graph_url: str | None
) -> tuple[DependencyStatus, DependencyStatus]:
    aut, graph = await asyncio.gather(probe.probe(aut_url), probe.probe(graph_url))
    return aut, graph


def is_ready(aut: DependencyStatus, graph: DependencyStatus) -> bool:
    """A dependency blocks readiness only when it is configured and unhealthy."""

    healthy = {DependencyStatus.OK, DependencyStatus.NOT_CONFIGURED}
    return aut in healthy and graph in healthy
