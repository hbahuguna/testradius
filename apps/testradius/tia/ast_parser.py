from pathlib import Path


class ASTParser:
    """Parses Python/JS/TS source files to extract functions, classes, imports."""

    SUPPORTED_EXTENSIONS = {".py", ".js", ".mjs", ".ts", ".tsx", ".jsx"}

    def parse(self, file_path: str | Path) -> dict:
        path = Path(file_path)
        if path.suffix not in self.SUPPORTED_EXTENSIONS:
            return {"functions": [], "classes": [], "imports": []}

        content = path.read_text()
        if path.suffix == ".py":
            return self._parse_python(content)
        elif path.suffix in (".js", ".mjs", ".jsx"):
            return self._parse_javascript(content)
        elif path.suffix in (".ts", ".tsx"):
            return self._parse_typescript(content)

        return {"functions": [], "classes": [], "imports": []}

    def _parse_python(self, content: str) -> dict:
        functions, classes, imports = [], [], []
        try:
            import ast
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    functions.append({"name": node.name, "lineno": node.lineno})
                elif isinstance(node, ast.AsyncFunctionDef):
                    functions.append({"name": node.name, "lineno": node.lineno, "async": True})
                elif isinstance(node, ast.ClassDef):
                    classes.append({"name": node.name, "lineno": node.lineno})
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        imports.append({"name": alias.name, "asname": alias.asname})
        except SyntaxError:
            pass
        return {"functions": functions, "classes": classes, "imports": imports}

    def _parse_javascript(self, content: str) -> dict:
        return self._parse_generic(content)

    def _parse_typescript(self, content: str) -> dict:
        return self._parse_generic(content)

    def _parse_generic(self, content: str) -> dict:
        functions, classes, imports = [], [], []
        import re
        func_pattern = re.compile(r"(?:async\s+)?function\s+(\w+)|(\w+)\s*=\s*(?:async\s+)?(?:function|\([^)]*\)\s*=>)")
        class_pattern = re.compile(r"class\s+(\w+)")
        import_pattern = re.compile(r"(?:import|require)\s+.*?['\"]([^'\"]+)['\"]")

        seen_funcs, seen_classes, seen_imports = set(), set(), set()
        for match in func_pattern.finditer(content):
            name = match.group(1) or match.group(2)
            if name and name not in seen_funcs:
                functions.append({"name": name, "lineno": content[:match.start()].count("\n") + 1})
                seen_funcs.add(name)

        for match in class_pattern.finditer(content):
            name = match.group(1)
            if name not in seen_classes:
                classes.append({"name": name, "lineno": content[:match.start()].count("\n") + 1})
                seen_classes.add(name)

        for match in import_pattern.finditer(content):
            name = match.group(1)
            if name not in seen_imports:
                imports.append({"name": name})
                seen_imports.add(name)

        return {"functions": functions, "classes": classes, "imports": imports}
