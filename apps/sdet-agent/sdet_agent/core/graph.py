"""Re-export the canonical 16-node SDET procedure graph.

We import directly from the existing workbench package to avoid divergence.
If that package is not importable in a given environment, the graph is also
mirrored here by `build_sdet_graph` for standalone use.
"""

from __future__ import annotations

try:
    from testsquad_workbench.sdet_procedure.graph import (  # type: ignore
        ProcedureGraph,
        Path,
        NodeRole,
        Node,
        Edge,
        build_sdet_graph,
        enumerate_paths,
    )
except ImportError:  # pragma: no cover - standalone fallback
    from ..reasoning._graph_fallback import (  # type: ignore
        ProcedureGraph,
        Path,
        NodeRole,
        Node,
        Edge,
        build_sdet_graph,
        enumerate_paths,
    )

__all__ = [
    "ProcedureGraph",
    "Path",
    "NodeRole",
    "Node",
    "Edge",
    "build_sdet_graph",
    "enumerate_paths",
]
