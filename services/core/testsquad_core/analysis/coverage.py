import xml.etree.ElementTree as ET
import logging
from typing import Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

class CoberturaParser:
    """Parses Cobertura XML reports into a line-level hit map."""
    
    def parse_report(self, file_path: str) -> Dict[str, Dict[int, int]]:
        """
        Parses the XML and returns:
        { "file_path": { line_number: hit_count } }
        """
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
        except Exception as e:
            logger.error(f"Failed to parse coverage report at {file_path}: {e}")
            return {}

        results = {}
        
        # Cobertura structure: packages -> package -> classes -> class -> lines -> line
        for package in root.findall(".//package"):
            for cls in package.findall(".//class"):
                filename = cls.get("filename")
                if not filename:
                    continue
                
                if filename not in results:
                    results[filename] = {}
                
                for line in cls.findall(".//line"):
                    line_num = int(line.get("number"))
                    hits = int(line.get("hits"))
                    results[filename][line_num] = hits
                    
        return results

class CoverageMapper:
    """Maps line-level coverage data to symbols in the Repo Brain."""
    
    def __init__(self, neo4j_client):
        self.neo4j = neo4j_client

    def map_coverage(self, project_id: int, coverage_data: Dict[str, Dict[int, int]]):
        """
        Iterates over the coverage data and updates Neo4j symbols.
        A symbol is marked as 'uncovered' if any of its lines have 0 hits.
        """
        logger.info(f"Mapping coverage data for project {project_id}...")
        print(f"DEBUG: Found coverage for {len(coverage_data)} files")
        
        for file_path, lines in coverage_data.items():
            # Calculate symbol-level coverage
            # We fetch all symbols for this file from Neo4j
            # Use ENDS WITH to handle different path roots (e.g. services/core/ vs local)
            query = """
            MATCH (p:Project {sql_id: $project_id})-[:CONTAINS]->(f:File)-[:DEFINES]->(s:Symbol)
            WHERE f.path ENDS WITH $path
            RETURN f.path as full_path, s.name as name, s.start_line as start, s.end_line as end
            """
            symbols = self.neo4j.query(query, {"project_id": project_id, "path": file_path})
            
            if not symbols:
                continue
                
            # Get the standardized path from the first symbol found
            standardized_path = symbols[0]["full_path"]
            logger.debug(f"Mapped {file_path} to {standardized_path}")
            
            for sym in symbols:
                start, end = sym["start"], sym["end"]
                # Filter coverage lines that fall within this symbol's range
                symbol_lines = {ln: hits for ln, hits in lines.items() if start <= ln <= end}
                
                if not symbol_lines:
                    continue
                
                total_lines = len(symbol_lines)
                covered_lines = sum(1 for hits in symbol_lines.values() if hits > 0)
                is_covered = covered_lines == total_lines
                coverage_score = covered_lines / total_lines if total_lines > 0 else 1.0
                
                # Update Neo4j
                self.neo4j.update_symbol_coverage(standardized_path, sym["name"], is_covered, coverage_score)
                logger.debug(f"Updated {sym['name']} coverage: {is_covered} ({coverage_score:.2f})")
