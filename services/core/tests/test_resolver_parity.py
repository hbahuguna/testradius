"""Story 11.3: Python/TypeScript attribution parity + language-based dispatch.

The instrumentation modules are loaded under a synthetic package so the tests
run without importing the ``testsquad_core.instrumentation`` package ``__init__``
(Neo4j / FastAPI deps) — the same isolation trick used by the other
path-loaded instrumentation tests.

Two guarantees are covered:

* a method hit credits the **method**, not its enclosing class, for *both*
  Python and TypeScript (innermost attribution);
* ``DiffParser.resolve_impacted_tests`` picks the resolver that matches the
  file's language when no resolver is injected (``.py`` -> Python AST,
  ``.ts/.tsx/.js/.jsx`` -> tree-sitter).
"""
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORE = _REPO_ROOT / "services" / "core" / "testsquad_core"
_INSTR = _CORE / "instrumentation"

_PKG = "parity_pkg"

# Line numbers matter for the assertions below.
_PY_SRC = (
    "class Calculator:\n"          # 1
    "    def add(self, a, b):\n"    # 2
    "        return a + b\n"        # 3  <- method body
    "\n"                            # 4  <- class body only
    "    def subtract(self, a, b):\n"
    "        return a - b\n"
)

_TS_SRC = (
    "class Calculator {\n"          # 1
    "  add(a: number, b: number) {\n"  # 2
    "    return a + b;\n"           # 3  <- method body
    "  }\n"                         # 4
    "\n"                            # 5  <- class body only
    "  subtract(a: number, b: number) {\n"
    "    return a - b;\n"
    "  }\n"
    "}\n"
)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mods():
    if _PKG not in sys.modules:
        pkg = types.ModuleType(_PKG)
        pkg.__path__ = [str(_INSTR)]
        sys.modules[_PKG] = pkg
    _load(f"{_PKG}.attribution", _INSTR / "attribution.py")
    _load(f"{_PKG}.symbol_resolver", _INSTR / "symbol_resolver.py")
    _load(f"{_PKG}.typescript_symbol_resolver", _INSTR / "typescript_symbol_resolver.py")
    _load(f"{_PKG}.diff_parser", _INSTR / "diff_parser.py")
    return types.SimpleNamespace(
        python=sys.modules[f"{_PKG}.symbol_resolver"],
        typescript=sys.modules[f"{_PKG}.typescript_symbol_resolver"],
        diff_parser=sys.modules[f"{_PKG}.diff_parser"],
    )


def _names(symbols):
    return [s.name for s in symbols]


def _single_line_diff(path, new_line):
    """A hunk that adds exactly ``new_line`` (1-based) to ``path``."""
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -1,{new_line - 1} +1,{new_line} @@\n"
        + "".join(f" ctx{i}\n" for i in range(new_line - 1))
        + "+added\n"
    )


# --- innermost attribution -------------------------------------------------

def test_typescript_method_hit_does_not_credit_class(mods, tmp_path):
    f = tmp_path / "calc.ts"
    f.write_text(_TS_SRC)
    resolver = mods.typescript.TypeScriptSymbolResolver()
    symbols = resolver.resolve_symbols(str(f), {"test": [3]})
    assert _names(symbols) == ["add"]


def test_typescript_class_body_hit_credits_class(mods, tmp_path):
    f = tmp_path / "calc.ts"
    f.write_text(_TS_SRC)
    resolver = mods.typescript.TypeScriptSymbolResolver()
    # Line 5 is inside the class body but outside every method.
    symbols = resolver.resolve_symbols(str(f), {"test": [5]})
    assert _names(symbols) == ["Calculator"]


def test_python_and_typescript_attribution_match(mods, tmp_path):
    py = tmp_path / "calc.py"
    py.write_text(_PY_SRC)
    ts = tmp_path / "calc.ts"
    ts.write_text(_TS_SRC)

    py_resolver = mods.python.SymbolResolver()
    ts_resolver = mods.typescript.TypeScriptSymbolResolver()

    # A method-only hit credits the method for both languages.
    assert _names(py_resolver.resolve_symbols(str(py), {"t": [3]})) == ["add"]
    assert _names(ts_resolver.resolve_symbols(str(ts), {"t": [3]})) == ["add"]

    # A class-body-only hit credits the class for both languages.
    assert _names(py_resolver.resolve_symbols(str(py), {"t": [4]})) == ["Calculator"]
    assert _names(ts_resolver.resolve_symbols(str(ts), {"t": [5]})) == ["Calculator"]


# --- language-based dispatch ----------------------------------------------

def test_select_resolver_by_extension(mods):
    select = mods.diff_parser.select_resolver
    assert type(select("pkg/a.py")).__name__ == "SymbolResolver"
    assert type(select("pkg/a.pyi")).__name__ == "SymbolResolver"
    assert type(select("pkg/a.ts")).__name__ == "TypeScriptSymbolResolver"
    assert type(select("pkg/a.tsx")).__name__ == "TypeScriptSymbolResolver"
    assert type(select("pkg/a.js")).__name__ == "TypeScriptSymbolResolver"
    assert type(select("pkg/a.jsx")).__name__ == "TypeScriptSymbolResolver"


def test_python_diff_uses_python_resolver_end_to_end(mods, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "calc.py").write_text(_PY_SRC)

    map_path = tmp_path / "test_method_map.json"
    map_path.write_text(json.dumps({"mappings": [
        {"test_file": "tests/test_calc.py",
         "symbols": [["add", "method", 2, 3, "src/calc.py"]]},
    ]}))

    # No injected resolver: the default must pick the Python resolver for `.py`.
    result = mods.diff_parser.DiffParser.resolve_impacted_tests(
        diff_text=_single_line_diff("src/calc.py", 3),
        test_method_map_path=str(map_path),
        source_root=str(tmp_path),
    )

    assert "add" in [s["name"] for s in result.changed_symbols]
    assert [t.test_file for t in result.impacted_tests] == ["tests/test_calc.py"]
    assert result.selected_count == 1
