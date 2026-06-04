import pytest
import subprocess
from unittest.mock import MagicMock, patch
from testsquad_core.analysis.git import GitAnalyzer

def test_git_aggregation_logic():
    analyzer = GitAnalyzer(repo_root=".")
    
    # Mock git log output
    # Format: AUTH:%ae\nfile_path
    mock_stdout = """AUTH:alice@test.com
file1.py
file2.py
AUTH:bob@test.com
file1.py
AUTH:alice@test.com
file1.py
"""
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = mock_stdout
        metrics = analyzer.get_churn_metrics()
        
        # Verify file1.py: 3 commits (alice, bob, alice), 2 unique authors (alice, bob)
        assert metrics["file1.py"]["commit_count"] == 3
        assert metrics["file1.py"]["author_count"] == 2
        
        # Verify file2.py: 1 commit (alice), 1 unique author (alice)
        assert metrics["file2.py"]["commit_count"] == 1
        assert metrics["file2.py"]["author_count"] == 1

def test_git_analyzer_handles_empty_log():
    analyzer = GitAnalyzer(repo_root=".")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = ""
        metrics = analyzer.get_churn_metrics()
        assert metrics == {}

def test_git_analyzer_handles_error():
    analyzer = GitAnalyzer(repo_root=".")
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        metrics = analyzer.get_churn_metrics()
        assert metrics == {}
