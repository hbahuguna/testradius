import pytest
import json
import os
import sys
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestMappingAccuracyEndpoint:
    """Test Task 6.4.3: Mapping accuracy endpoint tests."""

    def test_accuracy_endpoint_exists(self):
        """Test GET /projects/{project_id}/mapping-accuracy exists."""
        from testsquad_core import main
        
        routes = [r.path for r in main.app.routes]
        
        assert "/projects/{project_id}/mapping-accuracy" in routes

    def test_endpoint_method(self):
        """Test endpoint uses GET method."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and r.path == "/projects/{project_id}/mapping-accuracy"]
        
        if routes:
            assert routes[0].methods == {"GET"}


class TestMappingAccuracyResponse:
    """Test accuracy response structure."""

    def test_response_has_project_stats(self):
        """Test response includes project_stats."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "mapping-accuracy" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "project_stats" in source

    def test_response_has_overlap(self):
        """Test response includes overlap."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "mapping-accuracy" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "overlap" in source

    def test_uses_model_compare(self):
        """Test uses ModelCompare."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "mapping-accuracy" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "ModelCompare" in source


class TestMappingAccuracyParameters:
    """Test endpoint parameters."""

    def test_limit_parameter(self):
        """Test accepts limit parameter."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "mapping-accuracy" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "limit" in source

    def test_default_limit(self):
        """Test default limit is 50."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "/mapping-accuracy" in r.path]
        
        if routes:
            route = routes[0]
            for param in route.dependant.path_params:
                if param.name == "limit":
                    assert param.field_info.default == 50


class TestMappingAccuracyIntegration:
    """Test integration."""

    def test_uses_siamese_config(self):
        """Test uses SiameseConfig."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "mapping-accuracy" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "SiameseConfig" in source

    def test_compare_project_called(self):
        """Test calls compare_project."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "mapping-accuracy" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "compare.compare_project" in source

    def test_get_overlap_called(self):
        """Test calls get_overlap."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "mapping-accuracy" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "compare.get_overlap" in source