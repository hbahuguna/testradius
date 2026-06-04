import pytest
import os
from testsquad_core.discovery.engine import DiscoveryEngine
from testsquad_core.discovery.probes.dependency import DependencyProbe
from testsquad_core.discovery.probes.heuristic import HeuristicProbe
from testsquad_core.discovery.probes.code import CodeSignatureProbe
from testsquad_shared.api import FrameworkLabel, LanguageLabel

@pytest.mark.anyio
async def test_integration_discovery_on_self():
    # Run discovery on the current project directory (testsquad-v2 root)
    # We expect to find FastAPI, Pytest, etc.
    root_path = os.getcwd() # Should be the root of testsquad-v2
    
    probes = [
        DependencyProbe(),
        HeuristicProbe(),
        CodeSignatureProbe(),
    ]
    engine = DiscoveryEngine(probes)
    result = await engine.discover(root_path)
    
    assert result.primary_language == LanguageLabel.PYTHON
    
    labels = [res.label for res in result.detected_frameworks]
    assert FrameworkLabel.FASTAPI in labels
    assert FrameworkLabel.PYTEST in labels
    # Since we have docker-compose.yml
    assert FrameworkLabel.GENERIC in labels 
    
    # Check repo structure
    assert result.repo_structure == "monorepo"
