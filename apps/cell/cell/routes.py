from fastapi import APIRouter, Request, Response

from .health import is_ready, probe_dependencies
from .models import HealthResponse

router = APIRouter()


@router.get("/v1/health", response_model=HealthResponse, tags=["contract"])
async def health(request: Request, response: Response) -> HealthResponse:
    settings = request.app.state.settings
    aut, graph = await probe_dependencies(
        request.app.state.probe, settings.aut_health_url, settings.graph_health_url
    )
    ready = is_ready(aut, graph)
    response.status_code = 200 if ready else 503
    return HealthResponse(
        ready=ready,
        aut_status=aut,
        graph_status=graph,
        version=settings.version,
    )
