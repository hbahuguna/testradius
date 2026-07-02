import pytest
import tempfile
from pathlib import Path

from testsquad_workbench.generation.cli import (
    build_parser,
    generate,
    _find_significant_components,
    _sanitize_filename,
)
from testsquad_workbench.generation.html_parser import parse_html


SAMPLE_HTML = """<!DOCTYPE html>
<html>
<head><title>Login Page</title></head>
<body>
  <nav>
    <a href="/">Home</a>
    <a href="/about">About</a>
  </nav>
  <form id="login" data-testid="login-form">
    <input type="email" name="email" placeholder="Email" />
    <input type="password" name="password" placeholder="Password" />
    <button type="submit">Sign In</button>
  </form>
  <aside class="sidebar">
    <a href="/profile">Profile</a>
  </aside>
</body>
</html>"""


class TestGenerate:
    def test_find_significant_components(self):
        tree = parse_html(SAMPLE_HTML, url="http://example.com")
        components = _find_significant_components(tree, max_components=10)
        types = [c[1].component_type for c in components]
        assert "NavBar" in types
        assert "LoginForm" in types
        assert "Sidebar" in types

    async def test_generate_returns_all_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            url = f"file://{tmpdir}/test.html"
            html_path = Path(tmpdir) / "test.html"
            html_path.write_text(SAMPLE_HTML)

            files = await generate(url, tmpdir, name="LoginSuite")
            file_names = list(files.keys())

            assert any("LoginSuite" in f for f in file_names)
            assert any("LoginForm" in f for f in file_names)
            assert any("NavBar" in f for f in file_names)

    def test_generate_com_code(self):
        tree = parse_html(SAMPLE_HTML, url="http://example.com")
        components = _find_significant_components(tree)
        for element, classification in components:
            assert classification.confidence > 0
            assert classification.component_type != "GenericComponent"

    def test_sanitize_filename(self):
        assert _sanitize_filename("Hello World!") == "Hello_World_"
        assert _sanitize_filename("Test-Suite_1") == "Test-Suite_1"
        assert _sanitize_filename("") == ""

    def test_parser_generate_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["generate", "http://example.com"])
        assert args.command == "generate"
        assert args.url == "http://example.com"
