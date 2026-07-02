from pathlib import Path
import networkx as nx


class DependencyGraph:
    """Builds a file-level dependency graph using imports found by ASTParser."""

    def __init__(self):
        self.graph = nx.DiGraph()

    def build_from_files(self, files: dict[str, dict]):
        """files: {filepath: ast_result}"""
        for filepath, ast_info in files.items():
            self.graph.add_node(filepath)
            for imp in ast_info.get("imports", []):
                imp_name = imp.get("name", "")
                resolved = self._resolve_import(filepath, imp_name)
                if resolved:
                    self.graph.add_edge(filepath, resolved)

    def _resolve_import(self, source_file: str, import_name: str) -> str | None:
        source_dir = Path(source_file).parent
        candidates = [
            source_dir / f"{import_name}.py",
            source_dir / f"{import_name}/__init__.py",
            source_dir / f"{import_name}.js",
            source_dir / f"{import_name}/index.js",
            source_dir / f"{import_name}.ts",
            source_dir / f"{import_name}/index.ts",
        ]
        for c in candidates:
            if c.exists():
                return str(c.relative_to(Path.cwd()))
        return None

    def get_dependents(self, filepath: str) -> list[str]:
        if filepath not in self.graph:
            return []
        return list(nx.descendants(self.graph, filepath))

    def get_dependencies(self, filepath: str) -> list[str]:
        if filepath not in self.graph:
            return []
        return list(nx.ancestors(self.graph, filepath))
