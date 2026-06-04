import logging
import subprocess
import os
from typing import Dict, Set

logger = logging.getLogger(__name__)

class GitAnalyzer:
    def __init__(self, repo_root: str):
        self.repo_root = repo_root

    def get_churn_metrics(self, since_days: int = 90) -> Dict[str, Dict]:
        """
        Extracts churn (commit count) and author count per file from git history.
        Returns a dict: { "file_path": { "commits": int, "authors": set() } }
        """
        logger.info(f"Analyzing git history for {self.repo_root} (last {since_days} days)...")
        
        # Command to get author email and changed files per commit
        # %ae = author email, %n = newline, --name-only = list files
        cmd = [
            "git", "log", 
            f"--since={since_days} days ago", 
            "--no-merges", 
            "--pretty=format:AUTH:%ae", 
            "--name-only"
        ]
        
        try:
            result = subprocess.run(
                cmd, 
                cwd=self.repo_root, 
                capture_output=True, 
                text=True, 
                check=True
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Git log failed: {e}")
            return {}

        metrics = {}
        current_author = None
        
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
                
            if line.startswith("AUTH:"):
                current_author = line.replace("AUTH:", "")
            else:
                # This is a file path
                file_path = line
                if file_path not in metrics:
                    metrics[file_path] = {"commits": 0, "authors": set()}
                
                metrics[file_path]["commits"] += 1
                if current_author:
                    metrics[file_path]["authors"].add(current_author)

        # Convert sets to counts for simpler consumption
        final_metrics = {}
        for path, data in metrics.items():
            final_metrics[path] = {
                "commit_count": data["commits"],
                "author_count": len(data["authors"])
            }
            
        return final_metrics
