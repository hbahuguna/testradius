from pathlib import Path
from .ast_parser import ASTParser


class TestMapper:
    """Maps source files to their corresponding test files."""

    TEST_GLOB_PATTERNS = [
        "**/test_*.py", "**/*_test.py", "**/*.test.py",
        "**/*.spec.py",
        "**/test_*.js", "**/*.test.js", "**/*.spec.js",
        "**/test_*.ts", "**/*.test.ts", "**/*.spec.ts",
        "**/*.test.tsx", "**/*.spec.tsx",
    ]

    def __init__(self, repo_path: str | Path = Path.cwd()):
        self.repo_path = Path(repo_path)
        self.parser = ASTParser()
        self._test_files: list[dict] | None = None

    def _discover_test_files(self) -> list[dict]:
        if self._test_files is not None:
            return self._test_files

        results = []
        for pattern in self.TEST_GLOB_PATTERNS:
            for path in self.repo_path.glob(pattern):
                relative = path.relative_to(self.repo_path)
                parsed = self.parser.parse(path)
                results.append({
                    "path": str(relative),
                    "functions": parsed.get("functions", []),
                    "classes": parsed.get("classes", []),
                    "stem": path.stem,
                    "name": path.name,
                })
        self._test_files = results
        return results

    def find_tests_for_file(self, filepath: str) -> list[dict]:
        path = Path(filepath)
        stem = path.stem
        all_tests = self._discover_test_files()
        matches = []

        for test in all_tests:
            test_stem = test["stem"]
            test_name = test["name"]
            if (stem in test_stem or stem in test_name or
                test_stem.startswith("test_") and stem in test_stem or
                test_name.startswith(stem.replace("_", "_test_"))):
                matches.append(test)

        return matches

    def analyze_impact(self, changed_files: list[str]) -> dict:
        impacted_tests = []
        seen = set()

        for f in changed_files:
            tests = self.find_tests_for_file(f)
            for t in tests:
                if t["path"] not in seen:
                    impacted_tests.append(t)
                    seen.add(t["path"])

        return {
            "changed_files": changed_files,
            "impacted_tests": impacted_tests,
            "total_impacted": len(impacted_tests),
        }
