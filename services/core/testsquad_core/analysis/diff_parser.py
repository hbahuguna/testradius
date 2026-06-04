from dataclasses import dataclass
from typing import List, Set, Dict, Optional, Any

from .scorer import UnifiedScorer, Evidence
try:
    from testsquad_core.intelligence.embedder import Embedder
    from testsquad_core.graph.client import Neo4jClient
    EMBEDDER_AVAILABLE = True
except ImportError:
    EMBEDDER_AVAILABLE = False
    Embedder = None


@dataclass
class FileChange:
    """Represents a changed file in a diff."""
    path: str
    old_path: Optional[str]
    added_lines: Set[int]
    removed_lines: Set[int]
    is_binary: bool
    is_deleted: bool


@dataclass
class TestWithScore:
    """Represents a test with impact score."""
    test_name: str
    test_file: str
    confidence: float
    reason: str
    risk_score: float


class DiffParser:
    """Parses unified diffs and maps changed lines to symbols.
    
    Pure Python implementation for Python 3.7 compatibility.
    """

    def __init__(self, neo4j_client=None, scorer=None):
        self.neo4j = neo4j_client
        self.scorer = scorer or UnifiedScorer()

    def parse_diff(self, diff_text: str) -> List[FileChange]:
        """Parse unified diff format."""
        changes = []
        
        if not diff_text or not diff_text.strip():
            return changes
            
        current_file = None
        added_lines = set()
        removed_lines = set()
        old_path = None
        is_binary = False
        
        # State tracking
        old_line_num = 0
        new_line_num = 0
        
        lines = diff_text.split('\n')
        
        for line in lines:
            # File header detection
            if line.startswith('diff --git'):
                if current_file is not None:
                    changes.append(self._create_file_change(
                        current_file, old_path, added_lines, removed_lines, is_binary
                    ))
                added_lines = set()
                removed_lines = set()
                old_path = None
                is_binary = False
                old_line_num = 0
                new_line_num = 0
                continue
            
            if line.startswith('--- '):
                path = line[4:]
                if path.startswith('a/'):
                    path = path[2:]
                current_file = path
                continue
                
            if line.startswith('+++ '):
                path = line[4:]
                if path.startswith('b/'):
                    path = path[2:]
                current_file = path
                continue
                
            if line.startswith('rename from '):
                old_path = line[11:].strip()
                continue
                
            if line.startswith('new file mode') or line.startswith('similarity index'):
                continue
                
            if line.startswith('Binary files'):
                is_binary = True
                continue
                
            # Hunk header: @@ -old_start,old_count +new_start,new_count @@
            if line.startswith('@@'):
                # Parse @@ -start,count +start,count @@
                parts = line.split(' ')
                for part in parts:
                    if part.startswith('-') and ',' in part:
                        nums = part[1:].split(',')
                        old_line_num = int(nums[0])
                    elif part.startswith('+') and ',' in part:
                        nums = part[1:].split(',')
                        new_line_num = int(nums[0])
                continue
            
            # Content lines
            if line.startswith('+') and not line.startswith('+++'):
                added_lines.add(new_line_num)
                new_line_num += 1
            elif line.startswith('-') and not line.startswith('---'):
                removed_lines.add(old_line_num)
                old_line_num += 1
            elif line.startswith(' ') or line == '':
                if old_line_num > 0:
                    old_line_num += 1
                if new_line_num > 0:
                    new_line_num += 1
        
        # Add last file
        if current_file is not None:
            changes.append(self._create_file_change(
                current_file, old_path, added_lines, removed_lines, is_binary
            ))
        
        return changes

    def _create_file_change(
        self, path: str, old_path: Optional[str],
        added: Set[int], removed: Set[int], is_binary: bool
    ) -> FileChange:
        is_deleted = len(added) == 0 and len(removed) > 0
        return FileChange(
            path=path,
            old_path=old_path,
            added_lines=added,
            removed_lines=removed,
            is_binary=is_binary,
            is_deleted=is_deleted
        )

    def map_lines_to_symbols(
        self, file_path: str, changed_lines: List[int], project_id: int
    ) -> List[Dict]:
        """Map changed lines to symbols in Neo4j."""
        if not self.neo4j:
            return []

        query = """
        MATCH (s:Symbol)
        WHERE s.file_path ENDS WITH $file_path
          AND (
            $line_start <= s.start_line <= $line_end
            OR $line_start <= s.end_line <= $line_end
            OR s.start_line <= $line_start AND s.end_line >= $line_end
          )
        RETURN s.name AS symbol_name, s.type AS symbol_type,
               s.file_path AS file_path,
               s.start_line AS start_line, s.end_line AS end_line
        """

        symbols = []
        for line in changed_lines:
            result = self.neo4j.query(query, {
                "file_path": file_path,
                "line_start": line,
                "line_end": line
            })
            for record in result:
                if not any(s['symbol_name'] == record['symbol_name'] for s in symbols):
                    record['changed_lines'] = [line]
                    symbols.append(record)
                else:
                    for s in symbols:
                        if s['symbol_name'] == record['symbol_name']:
                            s['changed_lines'].append(line)
                            break

        return symbols

    def get_impact_tests(
        self,
        changed_symbols: List[Dict],
        project_id: int,
        embedder: Any = None,
        max_hops: int = 2,
        top_k: int = 10
    ) -> List[TestWithScore]:
        """Analyze changed symbols and find impacted tests using evidence fusion.
        
        Args:
            changed_symbols: List of symbol dicts with name, file_path, start_line, end_line
            project_id: Project ID
            embedder: Embedder instance (unused, kept for API compat)
            max_hops: Maximum call graph traversal depth (1-2)
            top_k: Number of top tests to return
            
        Returns:
            List of TestWithScore sorted by impact score
        """
        if not self.neo4j:
            return []

        all_evidence = []

        for symbol in changed_symbols:
            symbol_name = symbol.get('symbol_name')
            symbol_file = symbol.get('file_path')

            if not symbol_name or not symbol_file:
                continue

            all_evidence.extend(
                self._query_evidence(symbol_name, symbol_file, project_id)
            )

            all_evidence.extend(
                self._query_call_graph_evidence(symbol_name, project_id, max_hops)
            )

        scored = self.scorer.score_all(all_evidence)

        return [
            TestWithScore(
                test_name=r.test_name,
                test_file=r.test_file,
                confidence=r.confidence,
                reason=";".join(r.evidence_sources),
                risk_score=r.confidence,
            )
            for r in scored[:top_k]
        ]

    def _query_evidence(self, symbol_name: str, symbol_file: str, project_id: int) -> List[Evidence]:
        """Query all [:EVIDENCE] edges for a symbol."""
        if not self.neo4j:
            return []
        query = """
        MATCH (s:Symbol {file_path: $file_path})<-[e:EVIDENCE]-(t:TestSymbol)
        WHERE s.name = $symbol_name
        RETURN t.name AS test_name, t.file_path AS test_file,
               e.source AS source, e.confidence AS confidence
        """
        results = self.neo4j.query(query, {
            "file_path": symbol_file,
            "symbol_name": symbol_name,
        })
        evidence = []
        for r in results:
            evidence.append(Evidence(
                source=r["source"],
                test_name=r["test_name"],
                test_file=r["test_file"],
                symbol_name=symbol_name,
                confidence=r.get("confidence", 0.5),
                metadata={},
            ))
        return evidence

    def _query_call_graph_evidence(self, symbol_name: str, project_id: int, max_hops: int = 2) -> List[Evidence]:
        """Query call graph for transitive evidence."""
        if not self.neo4j:
            return []
        evidence = []
        for hops in range(1, max_hops + 1):
            source = "call_graph_1" if hops == 1 else "call_graph_2"
            query = f"""
            MATCH (s:Symbol {{name: $symbol_name}})-[:CALLS*{hops}..{hops}]->(dep:Symbol)
            MATCH (dep)<-[e:EVIDENCE]-(t:TestSymbol)
            WHERE NOT ( (t)-[:EVIDENCE]->(s) )
            RETURN DISTINCT t.name AS test_name, t.file_path AS test_file,
                            e.confidence AS confidence
            LIMIT 20
            """
            results = self.neo4j.query(query, {"symbol_name": symbol_name})
            for r in results:
                evidence.append(Evidence(
                    source=source,
                    test_name=r["test_name"],
                    test_file=r["test_file"],
                    symbol_name=symbol_name,
                    confidence=r.get("confidence", 0.3),
                    metadata={"graph_distance": hops},
                ))
        return evidence

    def _create_test_with_score(
        self,
        test_name: str,
        test_file: str,
        confidence: float,
        reason: str,
        risk_score: float
    ) -> TestWithScore:
        return TestWithScore(
            test_name=test_name,
            test_file=test_file,
            confidence=confidence,
            reason=reason,
            risk_score=risk_score
        )