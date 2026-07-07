from pathlib import Path
from typing import Any

from .git_analyzer import GitAnalyzer
from .test_mapper import TestMapper


class CoverageGapsAnalyzer:
    """Analyzes which changed files lack test coverage."""

    def __init__(self, repo_path: str | Path = Path.cwd()):
        self.repo_path = Path(repo_path)
        self.git = GitAnalyzer(repo_path)
        self.mapper = TestMapper(repo_path)

    def analyze(self, base: str = "main") -> dict[str, Any]:
        changed = self.git.get_changed_files(base=base)

        covered = []
        uncovered = []
        test_files = []
        seen_tests = set()

        for f in changed:
            tests = self.mapper.find_tests_for_file(f)
            if tests:
                covered.append(f)
                for t in tests:
                    if t["path"] not in seen_tests:
                        test_files.append(t)
                        seen_tests.add(t["path"])
            else:
                uncovered.append(f)

        coverage_pct = (len(covered) / len(changed) * 100) if changed else 100.0

        return {
            "base_branch": base,
            "total_changed": len(changed),
            "covered_count": len(covered),
            "uncovered_count": len(uncovered),
            "coverage_percent": round(coverage_pct, 1),
            "changed_files": changed,
            "covered_files": covered,
            "uncovered_files": uncovered,
            "impacted_test_files": test_files,
            "total_tests": len(test_files),
        }
