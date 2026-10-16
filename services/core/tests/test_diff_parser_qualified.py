"""Unit tests for G2: qualified-name changed-symbol resolution.

``instrumentation/diff_parser`` is loaded by path so these tests run without
importing the ``testsquad_core.instrumentation`` package ``__init__`` (Neo4j /
FastAPI / tree-sitter deps). A fake resolver is injected (``resolver=...``) so
no source files or tree-sitter runtime are required.
"""
import importlib.util
import json
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "testsquad_core"
    / "instrumentation"
    / "diff_parser.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("instrumentation_diff_parser", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def dp():
    return _load_module()


class _Sym:
    def __init__(self, name, start, end, symbol_type="function"):
        self.name = name
        self.symbol_type = symbol_type
        self.start_line = start
        self.end_line = end


class _FakeResolver:
    """Returns symbols keyed by a path suffix (no filesystem / tree-sitter)."""

    def __init__(self, by_suffix):
        self._by_suffix = by_suffix
        self.calls = []

    def get_symbols(self, full_path):
        self.calls.append(full_path)
        norm = full_path.replace("\\", "/")
        for suffix, syms in self._by_suffix.items():
            if norm.endswith(suffix):
                return list(syms)
        return []


def _write_map(tmp_path, mappings):
    path = tmp_path / "test_method_map.json"
    path.write_text(json.dumps({"mappings": mappings}))
    return str(path)


def _mapping(test_file, symbols):
    return {"test_file": test_file, "symbols": symbols}


def _single_line_diff(path, new_line, text="added"):
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -1,{new_line - 1} +1,{new_line} @@\n"
        + "".join(f" ctx{i}\n" for i in range(new_line - 1))
        + f"+{text}\n"
    )


class TestSameNameDifferentFiles:
    def test_same_named_symbols_do_not_cross_map(self, dp, tmp_path):
        # `get` exists in two different files with identical spans.
        map_path = _write_map(tmp_path, [
            _mapping("tests/test_a.py", [["get", "function", 1, 5, "src/a.py"]]),
            _mapping("tests/test_b.py", [["get", "function", 1, 5, "src/b.py"]]),
        ])
        resolver = _FakeResolver({"src/a.py": [_Sym("get", 1, 5)]})
        result = dp.DiffParser.resolve_impacted_tests(
            diff_text=_single_line_diff("src/a.py", 3),
            test_method_map_path=map_path,
            source_root="/repo",
            resolver=resolver,
        )
        assert [t.test_file for t in result.impacted_tests] == ["tests/test_a.py"]
        assert [t.test_file for t in result.unimpacted_tests] == ["tests/test_b.py"]
        assert result.selected_count == 1

    def test_evidence_line_does_not_leak_across_files(self, dp, tmp_path):
        # Two same-named symbols, but only b.py is changed -> only test_b.
        map_path = _write_map(tmp_path, [
            _mapping("tests/test_a.py", [["store", "function", 10, 20, "src/a.py"]]),
            _mapping("tests/test_b.py", [["store", "function", 10, 20, "src/b.py"]]),
        ])
        resolver = _FakeResolver({"src/b.py": [_Sym("store", 10, 20)]})
        result = dp.DiffParser.resolve_impacted_tests(
            diff_text=_single_line_diff("src/b.py", 12),
            test_method_map_path=map_path,
            source_root="/repo",
            resolver=resolver,
        )
        assert [t.test_file for t in result.impacted_tests] == ["tests/test_b.py"]
        assert result.changed_symbols[0]["file_path"] == "src/b.py"


class TestExactlyOneQualifiedSymbol:
    def test_two_gets_in_one_file_resolve_by_span(self, dp, tmp_path):
        # Same file, same name `get`, two distinct classes/spans.
        map_path = _write_map(tmp_path, [
            _mapping("tests/test_a.py", [["get", "function", 10, 15, "src/c.py"]]),
            _mapping("tests/test_b.py", [["get", "function", 30, 35, "src/c.py"]]),
        ])
        resolver = _FakeResolver({
            "src/c.py": [_Sym("get", 10, 15, "method"), _Sym("get", 30, 35, "method")],
        })
        result = dp.DiffParser.resolve_impacted_tests(
            diff_text=_single_line_diff("src/c.py", 12),
            test_method_map_path=map_path,
            source_root="/repo",
            resolver=resolver,
        )
        # Exactly one changed symbol, with a module-qualified name.
        assert len(result.changed_symbols) == 1
        assert result.changed_symbols[0]["name"] == "get"
        assert result.changed_symbols[0]["qualified_name"] == "src.c.get"
        assert result.changed_symbols[0]["start_line"] == 10
        assert [t.test_file for t in result.impacted_tests] == ["tests/test_a.py"]
        assert [t.test_file for t in result.unimpacted_tests] == ["tests/test_b.py"]

    def test_qualified_name_includes_module(self, dp, tmp_path):
        map_path = _write_map(tmp_path, [
            _mapping("tests/test_a.py", [["__init__", "function", 1, 4, "src/pkg/mod.py"]]),
        ])
        resolver = _FakeResolver({"src/pkg/mod.py": [_Sym("__init__", 1, 4, "method")]})
        result = dp.DiffParser.resolve_impacted_tests(
            diff_text=_single_line_diff("src/pkg/mod.py", 2),
            test_method_map_path=map_path,
            source_root="/repo",
            resolver=resolver,
        )
        assert result.changed_symbols[0]["qualified_name"] == "src.pkg.mod.__init__"


class TestContainmentRegression:
    def test_symbol_matched_when_only_interior_line_changed(self, dp, tmp_path):
        # Symbol spans 10-20; changed lines are {1, 15, 30}. The old min/max
        # shortcut only checked min(=1) and max(=30) -> wrongly excluded it.
        diff = (
            "diff --git a/src/f.py b/src/f.py\n"
            "--- a/src/f.py\n"
            "+++ b/src/f.py\n"
            "@@ -1,0 +1,1 @@\n"
            "+one\n"
            "@@ -10,0 +15,1 @@\n"
            "+fifteen\n"
            "@@ -20,0 +30,1 @@\n"
            "+thirty\n"
        )
        map_path = _write_map(tmp_path, [
            _mapping("tests/test_a.py", [["foo", "function", 10, 20, "src/f.py"]]),
        ])
        resolver = _FakeResolver({"src/f.py": [_Sym("foo", 10, 20)]})
        result = dp.DiffParser.resolve_impacted_tests(
            diff_text=diff,
            test_method_map_path=map_path,
            source_root="/repo",
            resolver=resolver,
        )
        assert [t.test_file for t in result.impacted_tests] == ["tests/test_a.py"]

    def test_unrelated_symbol_not_selected(self, dp, tmp_path):
        map_path = _write_map(tmp_path, [
            _mapping("tests/test_a.py", [["foo", "function", 10, 20, "src/f.py"]]),
            _mapping("tests/test_z.py", [["bar", "function", 40, 50, "src/f.py"]]),
        ])
        resolver = _FakeResolver({"src/f.py": [_Sym("foo", 10, 20), _Sym("bar", 40, 50)]})
        result = dp.DiffParser.resolve_impacted_tests(
            diff_text=_single_line_diff("src/f.py", 12),
            test_method_map_path=map_path,
            source_root="/repo",
            resolver=resolver,
        )
        assert [t.test_file for t in result.impacted_tests] == ["tests/test_a.py"]
        assert "tests/test_z.py" not in [t.test_file for t in result.impacted_tests]


class TestPathNormalization:
    def test_absolute_clone_path_matches_relative_diff(self, dp, tmp_path):
        # Map recorded during instrumentation under a clone root; diff is
        # repo-relative against a different source_root.
        map_path = _write_map(tmp_path, [
            _mapping("tests/test_a.py",
                     [["get", "function", 1, 5, "/tmp/testbed-custom-123/src/a.py"]]),
        ])
        resolver = _FakeResolver({"src/a.py": [_Sym("get", 1, 5)]})
        result = dp.DiffParser.resolve_impacted_tests(
            diff_text=_single_line_diff("src/a.py", 3),
            test_method_map_path=map_path,
            source_root="/home/me/repo",
            resolver=resolver,
        )
        assert [t.test_file for t in result.impacted_tests] == ["tests/test_a.py"]

    def test_source_root_prefix_stripped(self, dp, tmp_path):
        assert dp._canonical_path("/repo/src/a.py", "/repo") == "src/a.py"
        assert dp._canonical_path("./src/a.py", "/repo") == "src/a.py"
        assert dp._canonical_path("a\\b\\c.py", "/repo") == "a/b/c.py"
        assert dp._paths_match("/x/src/a.py", "src/a.py") is True


class TestSymbolFormats:
    def test_dict_form_symbols_supported(self, dp, tmp_path):
        map_path = _write_map(tmp_path, [
            _mapping("tests/test_a.py", [
                {"name": "get", "symbol_type": "method", "start_line": 1,
                 "end_line": 5, "file_path": "src/a.py"},
            ]),
        ])
        resolver = _FakeResolver({"src/a.py": [_Sym("get", 1, 5)]})
        result = dp.DiffParser.resolve_impacted_tests(
            diff_text=_single_line_diff("src/a.py", 3),
            test_method_map_path=map_path,
            source_root="/repo",
            resolver=resolver,
        )
        assert result.selected_count == 1

    def test_empty_diff_returns_empty_result(self, dp, tmp_path):
        map_path = _write_map(tmp_path, [])
        result = dp.DiffParser.resolve_impacted_tests(
            diff_text="",
            test_method_map_path=map_path,
            source_root="/repo",
            resolver=_FakeResolver({}),
        )
        assert result.total_tests == 0
        assert result.selected_count == 0
