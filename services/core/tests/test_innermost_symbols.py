"""Unit tests for G1 innermost-symbol attribution.

``symbol_resolver`` is loaded by path so the tests run without importing the
``testsquad_core.instrumentation`` package ``__init__`` (Neo4j/FastAPI deps).
"""
import importlib.util
import os
from pathlib import Path

import pytest

_RESOLVER_PATH = (
    Path(__file__).resolve().parents[1]
    / "testsquad_core"
    / "instrumentation"
    / "symbol_resolver.py"
)


def _load_resolver():
    spec = importlib.util.spec_from_file_location("symbol_resolver", _RESOLVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SymbolResolver()


@pytest.fixture()
def resolver():
    return _load_resolver()


def _write(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source)
    return str(path)


def _names(symbols):
    return [s.name for s in symbols]


def test_class_with_method(tmp_path, resolver):
    path = _write(tmp_path, "calc.py", (
        "class Calculator:\n"
        "    def add(self, a, b):\n"
        "        return a + b\n"
        "    \n"
        "    def subtract(self, a, b):\n"
        "        return a - b\n"
    ))
    # Line 3 is inside `add` only -> exactly `add`, never `Calculator`.
    symbols = resolver.resolve_symbols(path, {"test": [3]})
    assert _names(symbols) == ["add"]

    # Line 6 is inside `subtract` only -> exactly `subtract`.
    symbols = resolver.resolve_symbols(path, {"test": [6]})
    assert _names(symbols) == ["subtract"]

    # Blank class-level line 4 -> `Calculator` (innermost owner), no method.
    symbols = resolver.resolve_symbols(path, {"test": [4]})
    assert _names(symbols) == ["Calculator"]


def test_no_duplicate_parent_child_evidence(tmp_path, resolver):
    path = _write(tmp_path, "store.py", (
        "class Store:\n"
        "    def get(self, key):\n"
        "        return self._data[key]\n"
        "    \n"
        "    def put(self, key, value):\n"
        "        self._data[key] = value\n"
    ))
    symbols = resolver.resolve_symbols(path, {"test": [3]})
    assert len(symbols) == 1
    assert symbols[0].name == "get"


def test_multiple_covered_lines_attributed_independently(tmp_path, resolver):
    path = _write(tmp_path, "utils.py", (
        "class A:\n"
        "    def one(self):\n"
        "        pass\n"
        "    \n"
        "    def two(self):\n"
        "        pass\n"
        "    \n"
        "class B:\n"
        "    def three(self):\n"
        "        pass\n"
    ))
    # Lines in method bodies (3, 6, 10) + a class-level blank (4, inside A).
    symbols = resolver.resolve_symbols(path, {"test": [3, 4, 6, 10]})
    assert set(_names(symbols)) == {"one", "two", "three", "A"}


def test_each_symbol_appears_once(tmp_path, resolver):
    path = _write(tmp_path, "multi.py", (
        "def foo(a):\n"
        "    x = a + 1\n"
        "    y = x * 2\n"
        "    return y\n"
    ))
    symbols = resolver.resolve_symbols(path, {"test": [2, 3, 4]})
    assert _names(symbols).count("foo") == 1


def test_nested_function_credits_inner(tmp_path, resolver):
    path = _write(tmp_path, "outer.py", (
        "def outer():\n"
        "    def inner():\n"
        "        return 1\n"
        "    return inner()\n"
    ))
    # Line 3 inside `inner` -> inner only, not outer.
    symbols = resolver.resolve_symbols(path, {"test": [3]})
    assert _names(symbols) == ["inner"]
    # Line 4 inside `outer` (outside inner) -> outer.
    symbols = resolver.resolve_symbols(path, {"test": [4]})
    assert _names(symbols) == ["outer"]


def test_top_level_function_unchanged(tmp_path, resolver):
    path = _write(tmp_path, "plain.py", (
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "def subtract(a, b):\n"
        "    return a - b\n"
    ))
    symbols = resolver.resolve_symbols(path, {"add": [2, 3]})
    assert _names(symbols) == ["add"]


def test_lines_outside_symbols_ignored(tmp_path, resolver):
    path = _write(tmp_path, "misc.py", "def foo():\n    pass\n\n# comment\nx = 1")
    symbols = resolver.resolve_symbols(path, {"test": [1, 2, 5]})
    assert _names(symbols) == ["foo"]