import ast
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


@dataclass
class Symbol:
    """Represents a code symbol (function, class, method)."""
    name: str
    symbol_type: str
    file_path: str
    start_line: int
    end_line: int
    full_signature: Optional[str] = None


@dataclass
class TestSymbolMapping:
    """Mapping from test to symbols it covers."""
    test_name: str
    test_file: str
    covered_symbols: List[Symbol] = field(default_factory=list)


class CoverageTransformer:
    """Transforms line-level coverage data into symbol-level mapping."""

    def __init__(self, project_root: str = ""):
        self.project_root = project_root
        self._symbol_cache: Dict[str, List[Symbol]] = {}

    async def transform_and_store(self, neo4j_client, project_id: int, coverage_data: Dict[str, Any]) -> int:
        """Transform coverage data and store in Neo4j."""
        store = TestSymbolStore(neo4j_client)
        
        files = coverage_data.get("files", {})
        edges_created = 0
        
        for file_path, file_data in files.items():
            executed_lines = file_data.get("executed_lines", [])
            covered_lines = file_data.get("covered_lines", [])
            lines_covered = executed_lines or covered_lines
            
            if not lines_covered:
                continue
            
            test_file = file_path
            test_name = os.path.basename(test_file)
            if test_name.startswith("test_"):
                test_name = test_name[5:]
            elif test_name.endswith("_test.py"):
                test_name = test_name[:-8]
            test_name = os.path.splitext(test_name)[0]
            
            source_files = self._find_source_files_for_path(test_file)
            for src_file in source_files:
                symbols = self._extract_symbols_from_file(src_file)
                
                for symbol in symbols:
                    store._store_test_symbol_edge(
                        project_id=project_id,
                        test_name=test_name,
                        test_file=test_file,
                        symbol_name=symbol.name,
                        symbol_type=symbol.symbol_type,
                        symbol_file=symbol.file_path,
                        symbol_start=symbol.start_line,
                        symbol_end=symbol.end_line
                    )
                    edges_created += 1
        
        return edges_created

    def _find_source_files_for_path(self, test_file: str) -> List[str]:
        """Find source files from coverage data that a test file might test."""
        test_dir = os.path.dirname(test_file) or "."
        source_files = []
        
        if not os.path.exists(test_dir):
            return source_files
        
        for f in os.listdir(test_dir):
            if f.endswith(".py") and not f.startswith("test_") and not f.endswith("_test.py"):
                source_files.append(os.path.join(test_dir, f))
        
        return source_files

    def _extract_symbols_from_file(self, file_path: str) -> List[Symbol]:
        """Extract symbols from a source file."""
        if not os.path.exists(file_path):
            return []
        
        symbols = []
        try:
            with open(file_path, 'r') as f:
                source = f.read()
            
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(Symbol(
                        name=node.name,
                        symbol_type="function",
                        file_path=file_path,
                        start_line=node.lineno,
                        end_line=node.end_lineno or node.lineno
                    ))
                elif isinstance(node, ast.ClassDef):
                    symbols.append(Symbol(
                        name=node.name,
                        symbol_type="class",
                        file_path=file_path,
                        start_line=node.lineno,
                        end_line=node.end_lineno or node.lineno
                    ))
        except Exception:
            pass
        
        return symbols

    def transform(
        self,
        coverage_data: Dict[str, Any],
        test_file: Optional[str] = None
    ) -> List[TestSymbolMapping]:
        """Transform coverage data into test-symbol mappings."""
        mappings = []
        files = coverage_data.get("files", {})

        for file_path, file_data in files.items():
            abs_file_path = file_path
            if not os.path.isabs(file_path):
                abs_file_path = os.path.join(self.project_root, file_path)

            executed_lines = file_data.get("executed_lines", [])
            covered_lines = file_data.get("covered_lines", [])
            lines_covered = executed_lines or covered_lines

            if not lines_covered:
                continue

            is_test = self._is_test_file(file_path)

            if is_test:
                mapping = self._process_test_file(abs_file_path, lines_covered)
                if mapping:
                    mappings.append(mapping)
            else:
                test_files = self._get_test_files_for_source(abs_file_path)
                symbols = self._extract_symbols(abs_file_path, [])

                for test_f in test_files:
                    covered = self._map_lines_to_symbols(lines_covered, symbols)
                    if covered:
                        mappings.append(TestSymbolMapping(
                            test_name=self._extract_test_name(test_f),
                            test_file=test_f,
                            covered_symbols=covered
                        ))

        return mappings

    def _is_test_file(self, file_path: str) -> bool:
        """Check if a file is a test file."""
        basename = os.path.basename(file_path)
        return basename.startswith("test_") or basename.endswith("_test.py")

    def _process_test_file(
        self,
        file_path: str,
        lines_covered: List[int]
    ) -> Optional[TestSymbolMapping]:
        """Process a test file and find source symbols it covers."""
        test_functions = self._extract_test_functions(file_path)
        source_files = self._find_source_files_for_test(file_path)

        all_symbols = []
        for src_file in source_files:
            symbols = self._extract_symbols(src_file, [])
            all_symbols.extend(symbols)

        if test_functions and all_symbols:
            return TestSymbolMapping(
                test_name=self._extract_test_name(file_path),
                test_file=file_path,
                covered_symbols=all_symbols
            )

        return None

    def _extract_test_functions(self, file_path: str) -> List[Symbol]:
        """Extract test functions from a test file."""
        if not os.path.exists(file_path):
            return []

        symbols = []
        try:
            with open(file_path, 'r') as f:
                source = f.read()

            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                    symbols.append(Symbol(
                        name=node.name,
                        symbol_type="test_function",
                        file_path=file_path,
                        start_line=node.lineno,
                        end_line=node.end_lineno or node.lineno
                    ))
        except Exception:
            pass

        return symbols

    def _find_source_files_for_test(self, test_file: str) -> List[str]:
        """Find source files that a test file might be testing."""
        test_dir = os.path.dirname(test_file) or "."
        source_files = []

        if not os.path.exists(test_dir):
            return source_files

        for f in os.listdir(test_dir):
            if f.endswith(".py") and not f.startswith("test_") and not f.endswith("_test.py"):
                source_files.append(os.path.join(test_dir, f))

        return source_files

    def _extract_symbols(self, file_path: str, source_lines: List[str]) -> List[Symbol]:
        """Extract symbols from a source file."""
        if file_path in self._symbol_cache:
            return self._symbol_cache[file_path]

        if not os.path.exists(file_path):
            return []

        symbols = []
        try:
            with open(file_path, 'r') as f:
                source = f.read()

            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(Symbol(
                        name=node.name,
                        symbol_type="function",
                        file_path=file_path,
                        start_line=node.lineno,
                        end_line=node.end_lineno or node.lineno,
                        full_signature=self._get_function_signature(node)
                    ))
                elif isinstance(node, ast.ClassDef):
                    symbols.append(Symbol(
                        name=node.name,
                        symbol_type="class",
                        file_path=file_path,
                        start_line=node.lineno,
                        end_line=node.end_lineno or node.lineno
                    ))
        except Exception:
            pass

        self._symbol_cache[file_path] = symbols
        return symbols

    def _get_function_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        """Generate function signature string."""
        args = []
        for arg in node.args.args:
            annotation = ""
            if arg.annotation:
                try:
                    annotation = f": {ast.unparse(arg.annotation)}"
                except:
                    pass
            args.append(f"{arg.arg}{annotation}")

        returns = ""
        if node.returns:
            try:
                returns = f" -> {ast.unparse(node.returns)}"
            except:
                pass

        return f"def {node.name}({', '.join(args)}){returns}"

    def _get_test_files_for_source(self, source_file: str) -> List[str]:
        """Find test files that might test this source file."""
        base_name = os.path.basename(source_file)
        name_without_ext = os.path.splitext(base_name)[0]

        possible_tests = [
            f"test_{name_without_ext}.py",
            f"{name_without_ext}_test.py",
        ]

        test_files = []
        source_dir = os.path.dirname(source_file) or "."

        for test_pattern in possible_tests:
            test_path = os.path.join(source_dir, test_pattern)
            if os.path.exists(test_path):
                test_files.append(test_path)

        return test_files

    def _map_lines_to_symbols(self, covered_lines: List[int], symbols: List[Symbol]) -> List[Symbol]:
        """Map covered line numbers to the symbols they belong to."""
        covered = set(covered_lines)
        result = []

        for symbol in symbols:
            symbol_lines = set(range(symbol.start_line, symbol.end_line + 1))
            if symbol_lines & covered:
                result.append(symbol)

        return result

    def _extract_test_name(self, test_file: str) -> str:
        """Extract a test name from test file path."""
        basename = os.path.basename(test_file)
        name_without_ext = os.path.splitext(basename)[0]

        if name_without_ext.startswith("test_"):
            name_without_ext = name_without_ext[5:]

        return name_without_ext


class TestSymbolStore:
    """Stores and retrieves test-symbol mappings in Neo4j.
    
    DEPRECATED: Use Neo4jStore from neo4j_store.py instead.
    This class uses [:COVERS] relationships which are not queried by DiffParser.
    The new Neo4jStore uses [:EVIDENCE] relationships for compatibility.
    """

    def __init__(self, neo4j_client=None):
        warnings.warn(
            "TestSymbolStore is deprecated. Use Neo4jStore from testsquad_core.instrumentation.neo4j_store instead. "
            "TestSymbolStore uses [:COVERS] relationships which are not compatible with DiffParser queries. "
            "Neo4jStore uses [:EVIDENCE] relationships for proper impact analysis.",
            DeprecationWarning,
            stacklevel=2
        )
        self.neo4j_client = neo4j_client

    def store_mappings(self, mappings: List[TestSymbolMapping], project_id: int) -> int:
        """Store test-symbol mappings in Neo4j."""
        if not self.neo4j_client:
            print("Warning: Neo4j client not configured, skipping storage")
            return 0

        edges_created = 0

        for mapping in mappings:
            for symbol in mapping.covered_symbols:
                self._store_test_symbol_edge(
                    project_id=project_id,
                    test_name=mapping.test_name,
                    test_file=mapping.test_file,
                    symbol_name=symbol.name,
                    symbol_type=symbol.symbol_type,
                    symbol_file=symbol.file_path,
                    symbol_start=symbol.start_line,
                    symbol_end=symbol.end_line
                )
                edges_created += 1

        return edges_created

    def _store_test_symbol_edge(
        self,
        project_id: int,
        test_name: str,
        test_file: str,
        symbol_name: str,
        symbol_type: str,
        symbol_file: str,
        symbol_start: int,
        symbol_end: int
    ) -> None:
        """Store a single test-symbol edge in Neo4j."""
        if not self.neo4j_client:
            return

        query = """
        MERGE (t:TestSymbol {
            name: $test_name,
            file_path: $test_file,
            project_id: $project_id
        })
        MERGE (s:Symbol {
            name: $symbol_name,
            file_path: $symbol_file,
            project_id: $project_id
        })
        SET s.symbol_type = $symbol_type,
            s.start_line = $symbol_start,
            s.end_line = $symbol_end
        MERGE (t)-[:COVERS {source: 'instrumentation', confidence: 1.0}]->(s)
        """

        try:
            params = {
                "test_name": test_name,
                "test_file": test_file,
                "project_id": project_id,
                "symbol_name": symbol_name,
                "symbol_type": symbol_type,
                "symbol_file": symbol_file,
                "symbol_start": symbol_start,
                "symbol_end": symbol_end
            }
            self.neo4j_client.query(query, params)
        except Exception as e:
            print(f"Warning: Failed to store edge: {e}")

    def get_impacted_tests(
        self,
        project_id: int,
        changed_symbols: List[str]
    ) -> List[Dict[str, Any]]:
        """Get tests that cover the given symbols."""
        if not self.neo4j_client:
            return []

        query = """
        MATCH (t:TestSymbol)-[:COVERS]->(s:Symbol)
        WHERE s.project_id = $project_id
          AND s.name IN $changed_symbols
        RETURN t.name as test_name, t.file_path as test_file,
               count(s) as symbol_count,
               1.0 as confidence
        ORDER BY symbol_count DESC
        """

        try:
            params = {
                "project_id": project_id,
                "changed_symbols": changed_symbols
            }
            results = self.neo4j_client.query(query, params)
            return [
                {
                    "test_name": r["test_name"],
                    "test_file": r["test_file"],
                    "confidence": r["confidence"],
                    "symbol_count": r["symbol_count"]
                }
                for r in results
            ]
        except Exception as e:
            print(f"Warning: Failed to query impacted tests: {e}")
            return []