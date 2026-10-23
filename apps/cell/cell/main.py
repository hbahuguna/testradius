from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .agent.runtime import build_agent_session
from .config import Settings, get_settings
from .health import DependencyProbe, HttpProbe
from .policy.engine import PolicyEngine
from .routes import router
from .runs.orchestrator import Orchestrator
from .runs.state import RunStore
from .runs.tokens import RunTokenManager
from .secrets.broker import VaultBroker


def create_app(
    settings: Settings | None = None,
    probe: DependencyProbe | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    store = RunStore(settings.state_dir)
    secrets = VaultBroker(settings.vault_addr, settings.vault_token)
    orchestrator = Orchestrator(
        store,
        settings.state_dir,
        agent_factory=lambda run: build_agent_session(settings, secrets, run),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        orchestrator.resume_incomplete()
        yield

    # Docs UIs are deliberately disabled: they ship static assets and a browser
    # surface, which the cell must never have (ADR-002).
    app = FastAPI(
        title="TestRadius Factory Cell",
        version=settings.version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.probe = probe or HttpProbe(settings.probe_timeout_seconds)
    app.state.store = store
    app.state.tokens = RunTokenManager(
        settings.run_token_secret,
        settings.run_token_ttl_seconds,
        settings.run_token_issuer,
        settings.run_token_audience,
    )
    app.state.orchestrator = orchestrator
    app.state.policy = PolicyEngine()
    app.state.secrets = secrets
    app.include_router(router)
    return app


app = create_app()
