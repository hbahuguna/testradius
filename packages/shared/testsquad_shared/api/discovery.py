from enum import Enum
from typing import List, Optional, Dict
from pydantic import BaseModel, Field

class LanguageLabel(str, Enum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    GO = "go"
    UNKNOWN = "unknown"

class FrameworkLabel(str, Enum):
    FASTAPI = "fastapi"
    FLASK = "flask"
    DJANGO = "django"
    REACT = "react"
    VUE = "vue"
    NEXTJS = "nextjs"
    EXPRESS = "express"
    PYTEST = "pytest"
    ALEMBIC = "alembic"
    SQLALCHEMY = "sqlalchemy"
    POSTGRES = "postgres"
    NEO4J = "neo4j"
    GENERIC = "generic"

class DiscoveryProbeResult(BaseModel):
    label: FrameworkLabel
    version: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    source: str  # e.g., "package.json", "imports", "file_heuristic"

class FrameworkDiscovery(BaseModel):
    primary_language: LanguageLabel
    detected_frameworks: List[DiscoveryProbeResult] = []
    repo_structure: Optional[str] = None # e.g., "monorepo", "flat"
    metadata: Dict[str, str] = {}
