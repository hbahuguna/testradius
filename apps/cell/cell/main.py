from fastapi import FastAPI

from .config import Settings, get_settings
from .health import DependencyProbe, HttpProbe
from .routes import router


def create_app(
    settings: Settings | None = None,
    probe: DependencyProbe | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    # Docs UIs are deliberately disabled: they ship static assets and a browser
    # surface, which the cell must never have (ADR-002).
    app = FastAPI(
        title="TestRadius Factory Cell",
        version=settings.version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.probe = probe or HttpProbe(settings.probe_timeout_seconds)
    app.include_router(router)
    return app


app = create_app()
