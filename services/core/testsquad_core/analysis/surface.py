import logging
import os
from typing import List, Dict, Set
from testsquad_core.graph.client import Neo4jClient

logger = logging.getLogger(__name__)

class SurfaceDetector:
    def __init__(self, neo4j: Neo4jClient):
        self.neo4j = neo4j
        
        # Heuristic markers for API routes (Framework specific)
        self.api_markers = [
            "app.get", "app.post", "app.put", "app.delete", "app.patch", "app.route",
            "router.get", "router.post", "router.put", "router.delete", "router.patch", "router.route",
            "blueprint.route", "api.route"
        ]
        
        # Entry point file names
        self.entry_point_files = ["main.py", "app.py", "cli.py", "wsgi.py", "asgi.py", "__init__.py"]

    def detect_and_tag(self, project_id: int):
        """Orchestrate all surface detection strategies and tag nodes in Neo4j."""
        logger.info(f"Starting surface detection for project {project_id}...")
        
        # 1. Strategy: Decorator-based (API Routes)
        self._detect_via_decorators(project_id)
        
        # 2. Strategy: File-based (Entry point heuristics)
        self._detect_via_file_heuristics(project_id)
        
        # 3. Strategy: Graph-based (Orphan analysis)
        self._detect_via_orphan_analysis(project_id)
        
        logger.info("Surface detection complete.")

    def _detect_via_decorators(self, project_id: int):
        """Identifies API entry points based on framework decorators."""
        # Query all symbols with decorators
        query = """
        MATCH (p:Project {sql_id: $project_id})-[:CONTAINS]->(f:File)-[:DEFINES]->(s:Symbol)
        WHERE s.decorators IS NOT NULL AND size(s.decorators) > 0
        RETURN s.name as name, f.path as file_path, s.decorators as decorators
        """
        symbols = self.neo4j.query(query, {"project_id": project_id})
        
        for sym in symbols:
            for dec in sym["decorators"]:
                if any(marker in dec for marker in self.api_markers):
                    self.neo4j.tag_symbol_as_entry_point(sym["file_path"], sym["name"], "api")
                    logger.debug(f"Tagged {sym['name']} as API entry point via decorator {dec}")
                    break

    def _detect_via_file_heuristics(self, project_id: int):
        """Identifies entry points based on file names (e.g., main.py, cli.py)."""
        for file_name in self.entry_point_files:
            query = """
            MATCH (p:Project {sql_id: $project_id})-[:CONTAINS]->(f:File)-[:DEFINES]->(s:Symbol)
            WHERE f.path ENDS WITH $file_name
            RETURN s.name as name, f.path as file_path
            """
            symbols = self.neo4j.query(query, {"project_id": project_id, "file_name": file_name})
            
            surface_type = "cli" if "cli" in file_name else "export" if file_name == "__init__.py" else "entrypoint"
            
            for sym in symbols:
                self.neo4j.tag_symbol_as_entry_point(sym["file_path"], sym["name"], surface_type)
                logger.debug(f"Tagged {sym['name']} as {surface_type} via file heuristic {file_name}")

    def _detect_via_orphan_analysis(self, project_id: int):
        """
        Identifies potential entry points that have no internal callers.
        Note: We exclude files like 'utils.py' or 'internal/' to avoid noise.
        """
        query = """
        MATCH (p:Project {sql_id: $project_id})-[:CONTAINS]->(f:File)-[:DEFINES]->(s:Symbol)
        WHERE NOT ()-[:CALLS]->(s)
        AND NOT f.path CONTAINS 'test'
        AND NOT f.path CONTAINS 'util'
        AND s.is_entry_point IS NULL
        RETURN s.name as name, f.path as file_path
        """
        symbols = self.neo4j.query(query, {"project_id": project_id})
        
        for sym in symbols:
            self.neo4j.tag_symbol_as_entry_point(sym["file_path"], sym["name"], "orphan")
            logger.debug(f"Tagged {sym['name']} as orphan entry point (no internal callers)")
