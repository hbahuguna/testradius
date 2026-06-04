"""Instrumentation module for Test Impact Analysis.

This module provides functionality to:
- Clone and setup test repositories
- Run tests with coverage instrumentation
- Transform coverage data to symbol mappings
- Store test-symbol relationships in Neo4j

New classes (recommended):
- InstrumentationTransformer: transforms per-test coverage to symbol mappings
- Neo4jStore: stores mappings using [:EVIDENCE] relationships (compatible with DiffParser)

Deprecated (will be removed):
- CoverageTransformer: use InstrumentationTransformer instead
- TestSymbolStore: use Neo4jStore instead (uses incompatible [:COVERS] relationships)
"""

import warnings

# New imports - recommended
from .symbol_resolver import SymbolResolver, Symbol
from .transformer import InstrumentationTransformer
from .neo4j_store import Neo4jStore

# Plugin is lazy-loaded to avoid importing pytest at module level
# Use: pytest -p testsquad_core.instrumentation.plugin tests/

from .testbed_manager import TestbedManager, TestbedConfig, TestbedResult
from .service import InstrumentationService

__all__ = [
    # New classes (recommended)
    "SymbolResolver",
    "Symbol",
    "InstrumentationTransformer",
    "Neo4jStore",
    "PerTestCoveragePlugin",
    "TestbedManager",
    "TestbedConfig",
    "TestbedResult",
    "InstrumentationService"
]