import pytest
import tempfile
import os
import json
import sys


class TestPerTestCoveragePlugin:
    """Tests for the pytest plugin that collects per-test coverage."""

    def test_plugin_module_imports(self):
        """Verify the plugin module can be imported."""
        from testsquad_core.instrumentation.plugin import PerTestCoveragePlugin
        assert PerTestCoveragePlugin is not None

    def test_plugin_has_required_methods(self):
        """Verify the plugin has the required pytest hook methods."""
        from testsquad_core.instrumentation.plugin import PerTestCoveragePlugin
        plugin = PerTestCoveragePlugin()
        
        # Check the plugin has the expected methods
        assert hasattr(plugin, 'pytest_runtest_call')
        assert hasattr(plugin, 'pytest_runtest_teardown')
        assert hasattr(plugin, 'pytest_sessionfinish')

    def test_plugin_can_be_instantiated(self):
        """Verify the plugin can be instantiated without errors."""
        from testsquad_core.instrumentation.plugin import PerTestCoveragePlugin
        plugin = PerTestCoveragePlugin()
        
        # Check initial state
        assert plugin.coverage_data == {}
        assert plugin.current_test is None
        assert plugin.cov is None