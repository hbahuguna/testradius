"""Bundled docker-compose rendering for the local TestRadius backend (E3/T2).

Generates a minimal, self-contained compose project (core + db + neo4j) with
data volumes under the agent data dir and the user's repo bind-mounted into the
core container. Kept as plain YAML text so it needs no extra dependencies and
survives PyInstaller packaging (R1).
"""

from __future__ import annotations

import os
from typing import List, Optional

from .repo import RepoMount

DEFAULT_CORE_IMAGE = os.environ.get(
    "TIA_BACKEND_CORE_IMAGE", "ghcr.io/testsquad/testradius-core:latest"
)
DEFAULT_DB_IMAGE = "postgres:16"
DEFAULT_NEO4J_IMAGE = "neo4j:5"


def render_compose(
    data_dir: str,
    *,
    core_image: str = DEFAULT_CORE_IMAGE,
    core_port: int = 8000,
    db_image: str = DEFAULT_DB_IMAGE,
    neo4j_image: str = DEFAULT_NEO4J_IMAGE,
    repo: Optional[RepoMount] = None,
    demo_mode: bool = True,
    build_context: Optional[str] = None,
    build_dockerfile: Optional[str] = None,
) -> str:
    data_dir = os.path.abspath(data_dir)
    lines: List[str] = ["services:", "  core:"]
    if build_context:
        lines += [
            "    build:",
            f"      context: {build_context}",
        ]
        if build_dockerfile:
            lines.append(f"      dockerfile: {build_dockerfile}")
    else:
        lines.append(f"    image: {core_image}")
    lines += [
        "    restart: unless-stopped",
        "    ports:",
        f'      - "{core_port}:8000"',
        "    environment:",
        "      PYTHONPATH: /app:/app/packages/shared",
        "      DATABASE_URL: postgresql+asyncpg://testsquad:testsquad_password@db:5432/testsquad",
        "      NEO4J_URL: bolt://neo4j:7687",
        "      NEO4J_USER: neo4j",
        "      NEO4J_PASSWORD: testsquad_password",
        f'      DEMO_MODE: "{1 if demo_mode else 0}"',
    ]
    if repo is not None:
        lines += [
            f"      TESTRADIUS_LOCAL_PATH: {repo.container_path}",
            "    volumes:",
            f"      - {repo.host_path}:{repo.container_path}",
        ]
    lines += [
        "    depends_on:",
        "      - db",
        "      - neo4j",
        "  db:",
        f"    image: {db_image}",
        "    restart: unless-stopped",
        "    environment:",
        "      POSTGRES_USER: testsquad",
        "      POSTGRES_PASSWORD: testsquad_password",
        "      POSTGRES_DB: testsquad",
        "    volumes:",
        f"      - {data_dir}/postgres:/var/lib/postgresql/data",
        "  neo4j:",
        f"    image: {neo4j_image}",
        "    restart: unless-stopped",
        "    environment:",
        "      NEO4J_AUTH: neo4j/testsquad_password",
        '      NEO4J_PLUGINS: \'["apoc"]\'',
        "    volumes:",
        f"      - {data_dir}/neo4j:/data",
    ]
    return "\n".join(lines) + "\n"
