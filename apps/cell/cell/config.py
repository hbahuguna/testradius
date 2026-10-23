from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Cell configuration, sourced from ``CELL_*`` environment variables.

    Secret *values* never live here; only a broker reference or a short-lived
    token secret used to verify run-scoped tokens.
    """

    model_config = SettingsConfigDict(env_prefix="CELL_", extra="ignore")

    service_name: str = "testradius-cell"
    version: str = "0.1.0"

    # Verification material for run-scoped tokens (E1-S3). The production value
    # comes from the secrets broker; the default exists only for local tests.
    run_token_secret: str = "dev-only-change-me"
    run_token_issuer: str = "testradius-control-plane"
    run_token_audience: str = "testradius-cell"
    run_token_ttl_seconds: int = 3600

    # Optional dependency probes. When unset the dependency is reported as
    # ``not_configured`` and does not block readiness.
    aut_health_url: str | None = None
    graph_health_url: str | None = None
    probe_timeout_seconds: float = 1.0

    # Persistence for run state and SSE events. Compose mounts /workspace.
    state_dir: str | None = None

    # Secrets broker (ADR-005). Values are fetched on demand, never logged.
    vault_addr: str = "http://vault:8200"
    vault_token: str = "dev-root-token"

    workspace_dir: str = "/workspace"
    fixture_repo_path: str | None = "/workspace/fixture"
    max_run_duration_seconds: int = 3600
    max_agent_steps: int = 12
    max_agent_tokens: int = 12000


@lru_cache
def get_settings() -> Settings:
    return Settings()
