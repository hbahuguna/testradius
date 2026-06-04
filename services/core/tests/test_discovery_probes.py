import pytest
import os
from unittest.mock import patch, mock_open
from testsquad_core.discovery.probes.dependency import DependencyProbe
from testsquad_core.discovery.probes.heuristic import HeuristicProbe
from testsquad_core.discovery.probes.code import CodeSignatureProbe
from testsquad_shared.api import FrameworkLabel

@pytest.mark.anyio
async def test_dependency_probe_python_requirements():
    probe = DependencyProbe()
    requirements_content = "fastapi==0.109.0\npytest\n"
    
    with patch("os.path.exists", return_value=True):
        # We need to simulate different files. This is a bit tricky with patch.
        # Let's simplify and test specific methods or use a better mock.
        def side_effect(path):
            return "requirements.txt" in path

        with patch("os.path.exists", side_effect=side_effect):
            with patch("builtins.open", mock_open(read_data=requirements_content)):
                results = await probe.probe("/root")
                labels = [res.label for res in results]
                assert FrameworkLabel.FASTAPI in labels
                assert FrameworkLabel.PYTEST in labels

@pytest.mark.anyio
async def test_dependency_probe_js_package_json():
    probe = DependencyProbe()
    package_json = '{"dependencies": {"react": "18.2.0"}, "devDependencies": {"next": "14.1.0"}}'
    
    def side_effect(path):
        return "package.json" in path

    with patch("os.path.exists", side_effect=side_effect):
        with patch("builtins.open", mock_open(read_data=package_json)):
            results = await probe.probe("/root")
            labels = [res.label for res in results]
            assert FrameworkLabel.REACT in labels
            assert FrameworkLabel.NEXTJS in labels

@pytest.mark.anyio
async def test_heuristic_probe_django():
    probe = HeuristicProbe()
    def side_effect(path):
        return "manage.py" in path

    with patch("os.path.exists", side_effect=side_effect):
        results = await probe.probe("/root")
        labels = [res.label for res in results]
        assert FrameworkLabel.DJANGO in labels

@pytest.mark.anyio
async def test_code_signature_probe_fastapi():
    probe = CodeSignatureProbe()
    code_content = "from fastapi import FastAPI\napp = FastAPI()"
    
    # Mock scanning the root directory
    from unittest.mock import MagicMock
    mock_entry = MagicMock()
    mock_entry.is_file.return_value = True
    mock_entry.name = "main.py"
    mock_entry.path = "/root/main.py"

    with patch("os.scandir", return_value=[mock_entry]):
        with patch("builtins.open", mock_open(read_data=code_content)):
            results = await probe.probe("/root")
            labels = [res.label for res in results]
            assert FrameworkLabel.FASTAPI in labels

@pytest.mark.anyio
async def test_discovery_engine_recursive():
    from testsquad_core.discovery.engine import DiscoveryEngine
    from testsquad_core.discovery.probes.dependency import DependencyProbe
    
    mock_walk = [
        ("/root", ["ui"], []),
        ("/root/ui", ["nested"], []),
        ("/root/ui/nested", [], ["package.json"])
    ]
    
    def mock_open_side_effect(path, mode="r"):
        data = b""
        if "package.json" in path:
            data = b'{"dependencies": {"react": "18.0.0"}}'
        
        # Create a mock file object that supports read()
        m = mock_open(read_data=data).return_value
        if "b" not in mode:
            m.read.return_value = data.decode()
        return m

    with patch("os.walk", return_value=mock_walk):
        with patch("os.listdir", return_value=["ui"]):
            with patch("os.path.exists", return_value=True):
                with patch("builtins.open", side_effect=mock_open_side_effect):
                    engine = DiscoveryEngine([DependencyProbe()])
                    result = await engine.discover("/root")
                    labels = [res.label for res in result.detected_frameworks]
                    assert FrameworkLabel.REACT in labels
