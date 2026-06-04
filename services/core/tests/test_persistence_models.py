import pytest
from testsquad_shared.persistence.models import Project, Repository, Scan
from datetime import datetime

def test_project_model():
    project = Project(name="Test Project", description="A test project")
    assert project.name == "Test Project"
    assert project.description == "A test project"
    assert isinstance(project.created_at, datetime)

def test_repository_model():
    repo = Repository(project_id=1, url="https://github.com/test/repo", language="python")
    assert repo.url == "https://github.com/test/repo"
    assert repo.language == "python"
    assert repo.branch == "main"

def test_scan_model():
    scan = Scan(repository_id=1, status="RUNNING", sha="abc123")
    assert scan.status == "RUNNING"
    assert scan.sha == "abc123"

from testsquad_shared.persistence.models import StyleCapsule

def test_style_capsule_model():
    capsule = StyleCapsule(
        project_id=1,
        framework="pytest",
        foundational_patterns={"indent": 4},
        negative_patterns=["don't use hardcoded secrets"],
        reference_examples=[{"name": "test1", "code": "def test_x(): pass"}]
    )
    assert capsule.project_id == 1
    assert capsule.framework == "pytest"
    assert capsule.negative_patterns == ["don't use hardcoded secrets"]
