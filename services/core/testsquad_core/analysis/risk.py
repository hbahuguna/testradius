import math
import logging
from typing import List, Dict
from testsquad_shared.models.symbols import CodeSymbol

logger = logging.getLogger(__name__)

class RiskScorer:
    """Calculates the Priority Risk Index (PRI) for code symbols."""

    def calculate_pri(self, symbol_data: Dict) -> float:
        """
        Calculates PRI with safety for None values.
        """
        # 1. Complexity (LoC)
        start = symbol_data.get("start_line") or 0
        end = symbol_data.get("end_line") or 0
        loc = max(1, end - start)
        
        # 2. Churn (Log scale)
        commits = symbol_data.get("commit_count") or 0
        churn_factor = math.log(commits + math.e)
        
        # 3. Stability
        authors = max(1, symbol_data.get("author_count") or 1)
        
        # 4. Coverage Gap
        coverage = symbol_data.get("coverage_score")
        if coverage is None:
            coverage = 1.0 # Assume covered if no data (conservative risk)
        gap_factor = 2.0 - coverage
        
        # 5. Impact
        is_entry = symbol_data.get("is_entry_point") or False
        surface_boost = 2.0 if is_entry else 1.0
        
        # Calculate raw PRI
        pri = loc * churn_factor * authors * gap_factor * surface_boost
        
        return round(pri, 2)

    def score_symbols(self, project_id: int, neo4j_client) -> List[Dict]:
        """Fetch all symbols for a project, calculate PRI, and return them."""
        logger.info(f"Scoring all symbols for project {project_id}...")
        
        # Fetch symbols with all necessary metrics
        query = """
        MATCH (p:Project {sql_id: $project_id})-[:CONTAINS]->(f:File)-[:DEFINES]->(s:Symbol)
        RETURN 
            elementId(s) as node_id,
            s.name as name,
            s.start_line as start_line,
            s.end_line as end_line,
            s.commit_count as commit_count,
            s.author_count as author_count,
            s.coverage_score as coverage_score,
            s.is_entry_point as is_entry_point
        """
        raw_symbols = neo4j_client.query(query, {"project_id": project_id})
        
        scored_data = []
        for symbol in raw_symbols:
            pri = self.calculate_pri(symbol)
            scored_data.append({
                "node_id": symbol["node_id"],
                "pri": pri
            })
            
        return scored_data
