"""
Pytest plugin for per-test coverage collection.

Usage: pytest --tia-output=coverage.json -p testsquad_core.instrumentation.plugin tests/
"""
import pytest
import coverage
import json
import os
import sys


class PerTestCoveragePlugin:
    """Pytest plugin that collects coverage data per test."""
    
    def __init__(self):
        self.coverage_data = {}
        self.current_test = None
        self.cov = None
    
    def pytest_configure(self, config):
        """Register our custom marker."""
        config.addinivalue_line(
            "markers", "tia: per-test coverage collection"
        )
    
    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_call(self, item):
        """Start coverage measurement before test execution."""
        self.current_test = item.nodeid
        
        # Create fresh coverage instance for this test
        self.cov = coverage.Coverage(
            data_file=None,  # Don't persist to file
            auto_data=False
        )
        self.cov.start()
    
    @pytest.hookimpl(trylast=True)
    def pytest_runtest_teardown(self, item, nextitem):
        """Stop coverage and collect data after test execution."""
        if self.cov is None:
            return
            
        self.cov.stop()
        
        # Get the coverage data
        data = self.cov.get_data()
        
        # Convert to our format: {filepath: [covered_lines]}
        file_coverage = {}
        for filename in data.measured_files():
            try:
                lines = data.lines(filename)
                if lines:
                    file_coverage[filename] = lines
            except Exception:
                pass
        
        # Store if there's any coverage
        if file_coverage:
            self.coverage_data[item.nodeid] = file_coverage
        
        # Erase for next test
        self.cov.erase()
        self.cov = None
        self.current_test = None
    
    def pytest_sessionfinish(self, session, exitstatus):
        """Write coverage data to file at end of session."""
        output_file = session.config.getoption("--tia-output", default=None)
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(self.coverage_data, f)


def pytest_addoption(parser):
    """Add custom command line option."""
    parser.addoption(
        "--tia-output",
        action="store",
        default=None,
        help="Output file for per-test coverage data"
    )


def pytest_configure(config):
    """Register the plugin."""
    config.plugin.registerinstance(PerTestCoveragePlugin())


# Make this a proper pytest plugin
pytest_plugins = ["testsquad_core.instrumentation.plugin"]