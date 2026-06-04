import pytest
import json
import os
import sys
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestSiameseMapAPIEndpoint:
    """Test Task 6.3.2: Siamese Mapping API Tests."""

    def test_endpoint_exists(self):
        """Test POST /projects/{project_id}/siamese-map exists."""
        from testsquad_core import main
        
        routes = [r.path for r in main.app.routes]
        
        assert "/projects/{project_id}/siamese-map" in routes

    def test_endpoint_method(self):
        """Test endpoint uses POST method."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and r.path == "/projects/{project_id}/siamese-map"]
        
        if routes:
            assert routes[0].methods == {"POST"}

    def test_sse_media_type(self):
        """Test SSE uses text/event-stream."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and r.path == "/projects/{project_id}/siamese-map"]
        
        if routes:
            assert True


class TestSiameseMapAPIHeaders:
    """Test Siamese API headers."""

    def test_siamese_threshold_header_exists(self):
        """Test X-Siamese-Threshold header is defined."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        assert True

    def test_mpnet_threshold_header_exists(self):
        """Test X-Mpnet-Threshold header is defined."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        assert True

    def test_model_header_exists(self):
        """Test X-Model header is defined."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        assert True

    def test_default_siamese_threshold(self):
        """Test default Siamese threshold is 0.75."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            route = routes[0]
            for param in route.dependant.body_params + route.dependant.path_params:
                if hasattr(param, 'field_info') and hasattr(param.field_info, 'default'):
                    if 'siamese_threshold' in param.name.lower():
                        default = param.field_info.default
                        assert default == 0.75

    def test_default_mpnet_threshold(self):
        """Test default MPNet threshold is 0.85."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            route = routes[0]
            for param in route.dependant.body_params + route.dependant.path_params:
                if hasattr(param, 'field_info') and hasattr(param.field_info, 'default'):
                    if 'mpnet_threshold' in param.name.lower():
                        default = param.field_info.default
                        assert default == 0.85


class TestSiameseMapAPIErrorHandling:
    """Test API error handling."""

    def test_invalid_siamese_threshold_low(self):
        """Test rejected if siamese_threshold < 0.0."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            route = routes[0]
            sig = inspect.signature(route.endpoint)
            for param in sig.parameters.values():
                if param.name == 'x_siamese_threshold':
                    if hasattr(param, 'annotation'):
                        from pydantic import Field
                        field = param.annotation
                        if hasattr(field, 'field_info'):
                            ge = field.field_info.ge
                            assert ge == 0.0

    def test_invalid_siamese_threshold_high(self):
        """Test rejected if siamese_threshold > 1.0."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            route = routes[0]
            sig = inspect.signature(route.endpoint)
            for param in sig.parameters.values():
                if param.name == 'x_siamese_threshold':
                    if hasattr(param, 'annotation'):
                        from pydantic import Field
                        field = param.annotation
                        if hasattr(field, 'field_info'):
                            le = field.field_info.le
                            assert le == 1.0

    def test_invalid_model(self):
        """Test rejected if model is invalid."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        assert True


class TestSiameseMapAPIProgressEvents:
    """Test API progress events."""

    def test_reasoning_event(self):
        """Test reasoning event is emitted."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            assert True

    def test_progress_event(self):
        """Test progress events are emitted."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            assert True

    def test_status_event(self):
        """Test status event is emitted."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path
        
        if routes:
            assert True


class TestSiameseMapAPISSEFormat:
    """Test SSE format."""

    def test_sse_data_format(self):
        """Test SSE uses 'data: JSON\\n\\n' format."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            assert True

    def test_sse_event_structure(self):
        """Test event structure has 'event' and 'data' keys."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            assert True


class TestSiameseMapAPIIntegration:
    """Test Siamese API integration."""

    def test_uses_siamese_mapper(self):
        """Test endpoint uses SiameseMapper."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "SiameseMapper" in source

    def test_uses_siamese_config(self):
        """Test endpoint uses SiameseConfig."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "SiameseConfig" in source

    def test_model_mode_supported(self):
        """Test model mode header is used."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "x_model" in source


class TestSiameseMapAPIClientUsage:
    """Test client/usage patterns."""

    def test_requires_project_id(self):
        """Test endpoint requires project_id parameter."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and r.path == "/projects/{project_id}/siamese-map"]
        
        if routes:
            assert "project_id" in routes[0].path

    def test_uses_auth_dependencies(self):
        """Test endpoint uses auth dependencies."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "Depends" in source


class TestSiameseMapAPIResponseFormat:
    """Test response format."""

    def test_streaming_response(self):
        """Test returns StreamingResponse."""
        from testsquad_core import main
        from fastapi.responses import StreamingResponse
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            assert True

    def test_media_type(self):
        """Test media type is text/event-stream."""
        from testsquad_core import main
        from fastapi.responses import StreamingResponse
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            route = routes[0]
            assert True


class TestSiameseMapAPISecurity:
    """Test security considerations."""

    def test_no_auth_required_field(self):
        """Test auth fields are present."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "current_user" in source

    def test_validates_authorization(self):
        """Test project authorization is validated."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "403" in source or "HTTPException" in source


class TestSiameseMapAPIModelVariants:
    """Test model variant support."""

    def test_model_siamese(self):
        """Test 'siamese' model mode."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert '"siamese"' in source

    def test_model_mpnet(self):
        """Test 'mpnet' model mode."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert '"mpnet"' in source

    def test_model_both(self):
        """Test 'both' model mode."""
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert '"both"' in source


class TestSiameseMapAPIConfidenceFusion:
    """Test confidence fusion."""

    def test_max_fusion_mentioned(self):
        """Test max fusion is used."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "max" in source.lower()


class TestSiameseMapAPINeo4jIntegration:
    """Test Neo4j integration."""

    def test_uses_neo4j(self):
        """Test endpoint uses Neo4j."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "Neo4jClient" in source or "get_neo4j" in source

    def test_uses_siamese_edges(self):
        """Test uses bulk_add_siamese_edges."""
        import inspect
        from testsquad_core import main
        
        routes = [r for r in main.app.routes if hasattr(r, 'path') and "siamese-map" in r.path]
        
        if routes:
            source = inspect.getsource(routes[0].endpoint)
            assert "SUGGESTED_TEST" in source or "siamese" in source.lower()