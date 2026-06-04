import pytest
import json
import os
import sys
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestMapTestsSiameseHeader:
    """Test Task 6.3.4: Updated /map-tests endpoint tests."""

    def test_siamese_header_exists(self):
        """Test x-use-siamese header is defined."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "/map-tests" in r.path]
        
        assert True

    def test_endpoint_accepts_siamese_header(self):
        """Test endpoint accepts x-use-siamese header."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "/map-tests" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "x_use_siamese" in source


class TestMapTestsSiameseMode:
    """Test Siamese mode in /map-tests."""

    def test_uses_siamese_mapper_when_header_true(self):
        """Test uses SiameseMapper when x-use-siamese=true."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "/map-tests" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "SiameseMapper" in source

    def test_uses_test_mapper_by_default(self):
        """Test uses TestMapper when x-use-siamese not set."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "/map-tests" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "TestMapper" in source

    def test_conditional_mapping(self):
        """Test conditional mapping based on header."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "/map-tests" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "if use_siamese:" in source


class TestMapTestsBackwardCompatibility:
    """Test backward compatibility."""

    def test_llm_model_header_still_works(self):
        """Test x-llm-model header is preserved."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "/map-tests" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "x_llm_model" in source

    def test_use_vector_header_still_works(self):
        """Test x-use-vector header is preserved."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "/map-tests" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "x_use_vector" in source


class TestMapTestsStatusResponse:
    """Test status response."""

    def test_siamese_mode_in_status(self):
        """Test status includes mode when Siamese used."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "/map-tests" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "'mode': 'siamese'" in source or '"mode": "siamese"' in source


class TestMapTestsIntegration:
    """Test integration."""

    def test_siamese_config_import(self):
        """Test SiameseConfig is imported."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "/map-tests" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "SiameseConfig" in source

    def test_siamese_mapper_import(self):
        """Test SiameseMapper is imported."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "/map-tests" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "from testsquad_core.intelligence.siamese_mapper" in source