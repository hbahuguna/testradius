import pytest
from testsquad_core.analysis.summarizer import SymbolSummarizer


class TestSymbolSummarizer:
    """Test suite for SymbolSummarizer (analysis module)."""

    @pytest.fixture
    def summarizer(self):
        return SymbolSummarizer()

    # --- Test docstring extraction ---

    def test_python_docstring_previous_line(self, summarizer):
        """Test Python docstring on line before definition."""
        content = '''"""Creates a new user."""
def create_user(name):
    return {}
'''
        symbol = {"name": "create_user", "type": "function", "start_line": 2}
        result = summarizer.summarize_product(content, symbol)
        assert "Creates a new user" in result

    def test_python_docstring_same_line(self, summarizer):
        """Test Python docstring on same line as definition."""
        content = 'def create_user(name):\n    """Creates a new user."""\n    return {}'
        symbol = {"name": "create_user", "type": "function", "start_line": 2}
        result = summarizer.summarize_product(content, symbol)
        assert "Creates a new user" in result

    def test_python_docstring_multiline(self, summarizer):
        """Test Python multi-line docstring."""
        content = '''"""Process user data.

Args:
    data: User input
"""
def process_data(data):
    return data'''
        symbol = {"name": "process_data", "type": "function", "start_line": 4}
        result = summarizer.summarize_product(content, symbol)
        assert "Process user data" in result

    # --- Test comment extraction ---

def test_adjacent_comments(self, summarizer):
        """Test extraction of comments before definition."""
        content = '# Validate email format\ndef validate_email(email):\n    return True'
        symbol = {"name": "validate_email", "type": "function", "start_line": 2}
        result = summarizer.summarize_product(content, symbol)
        assert "Validate email" in result

    def test_no_comments(self, summarizer):
        """Test when no comments available."""
        content = '''def foo():
    pass'''
        symbol = {"name": "foo", "type": "function", "start_line": 2}
        result = summarizer.summarize_product(content, symbol)
        assert "foo" in result

    # --- Test signature building ---

    def test_signature_with_params(self, summarizer):
        """Test signature building with parameters."""
        content = ""
        symbol = {
            "name": "create_user",
            "type": "function",
            "start_line": 1,
            "parameters": [
                {"name": "name", "type": "str"},
                {"name": "email", "type": "str"}
            ],
            "return_type": "dict"
        }
        result = summarizer.summarize_product(content, symbol)
        assert "create_user(name: str" in result
        assert "dict" in result

    def test_signature_without_params(self, summarizer):
        """Test signature without parameters."""
        content = ""
        symbol = {"name": "get_users", "type": "function", "start_line": 1}
        result = summarizer.summarize_product(content, symbol)
        assert "get_users(...)" in result

    def test_class_signature(self, summarizer):
        """Test class signature."""
        content = ""
        symbol = {"name": "User", "type": "class", "start_line": 1}
        result = summarizer.summarize_product(content, symbol)
        assert "class User" in result

    # --- Test test description parsing ---

    def test_pytest_test_name(self, summarizer):
        """Test pytest test function name parsing."""
        content = "def test_user_creation():\n    pass"
        symbol = {"name": "test_user_creation", "type": "function", "start_line": 2}
        result = summarizer.summarize_test(content, symbol)
        assert "Tests user creation" in result

    def test_jest_it_description(self, summarizer):
        """Test Jest it() description."""
        content = "it('should create user', () => {\n});"
        symbol = {"name": "should_create_user", "type": "function", "start_line": 2}
        result = summarizer.summarize_test(content, symbol)
        assert "should create user" in result

    def test_jest_test_description(self, summarizer):
        """Test Jest test() description."""
        content = "test('validates email', () => {});"
        symbol = {"name": "validates_email", "type": "function", "start_line": 2}
        result = summarizer.summarize_test(content, symbol)
        assert "validates email" in result

    # --- Test fixtures extraction ---

    def test_extract_fixtures_beforeEach(self, summarizer):
        """Test fixture extraction from beforeEach."""
        lines = ["beforeEach(() => {", " // setup"]
        result = summarizer._extract_fixtures(lines, 2)
        assert result and "beforeEach" in result

    def test_extract_fixtures_describe(self, summarizer):
        """Test fixture extraction from describe."""
        lines = ["describe('User', () => {", " // tests"]
        result = summarizer._extract_fixtures(lines, 2)
        assert result and "describe" in result

    # --- Test graceful degradation ---

    def test_empty_file(self, summarizer):
        """Test graceful degradation for empty file."""
        content = ""
        symbol = {"name": "foo", "type": "function", "start_line": 1}
        result = summarizer.summarize_product(content, symbol)
        assert "foo" in result

    def test_line_out_of_bounds(self, summarizer):
        """Test graceful degradation when line is out of file bounds."""
        content = "def foo():\n    pass"
        symbol = {"name": "foo", "type": "function", "start_line": 100}
        result = summarizer.summarize_product(content, symbol)
        assert "foo" in result

    # --- Test cross-language consistency ---

    def test_python_js_similarity(self, summarizer):
        """Test that Python and JS produce similar summary format."""
        # Python
        py_content = '''"""Create a new user."""
def create_user(name):
    pass'''
        py_symbol = {"name": "create_user", "type": "function", "start_line": 2}
        py_result = summarizer.summarize_product(py_content, py_symbol)
        
        # JS Signature fallback (JS docstrings in function body are known limitation)
        js_content = "function createUser(name) {\n    return {};\n}"
        js_symbol = {"name": "createUser", "type": "function", "start_line": 2}
        js_result = summarizer.summarize_product(js_content, js_symbol)
        
        # Both should produce useful output
        assert "create" in py_result.lower()
        assert "create" in js_result.lower()


class TestSymbolSummarizerEdgeCases:
    """Edge case tests for SymbolSummarizer."""

    @pytest.fixture
    def summarizer(self):
        return SymbolSummarizer()

    def test_unicode_in_docstring(self, summarizer):
        """Test handling of unicode in docstrings."""
        content = 'def foo():\n    """Creates user 🎉"""\n    pass'
        symbol = {"name": "foo", "type": "function", "start_line": 2}
        result = summarizer.summarize_product(content, symbol)
        assert "foo" in result

    def test_empty_symbol_name(self, summarizer):
        """Test handling of empty symbol name."""
        content = "def foo():\n    pass"
        symbol = {"name": "", "type": "function", "start_line": 2}
        result = summarizer.summarize_product(content, symbol)
        assert result  # Should handle gracefully