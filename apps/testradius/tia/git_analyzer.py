import subprocess
from pathlib import Path


class GitAnalyzer:
    """Analyzes git diff to find changed files and code."""

    def __init__(self, repo_path: str | Path = Path.cwd()):
        self.repo_path = Path(repo_path)

    def get_changed_files(self, base: str = "main") -> list[str]:
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", base, "--relative"],
                capture_output=True, text=True, check=True, cwd=self.repo_path,
            )
            files = [f for f in result.stdout.splitlines() if f]
            return files
        except subprocess.CalledProcessError:
            return []

    def get_diff(self, base: str = "main") -> str:
        try:
            result = subprocess.run(
                ["git", "diff", base],
                capture_output=True, text=True, check=True, cwd=self.repo_path,
            )
            return result.stdout
        except subprocess.CalledProcessError:
            return ""
