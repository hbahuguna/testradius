"""Unit tests for S2: runtime + static fusion.

Two layers are covered:

* ``analysis/fusion.py`` — the pure union/confidence logic (loaded by path).
* ``graph/ingestor.py`` — test files are indexed for their import edges only,
  so static reachability (test -> product module) exists without polluting the
  product-symbol graph.
"""
import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ANALYSIS = _REPO_ROOT / "services" / "core" / "testsquad_core" / "analysis"

# testsquad_shared (imported by the Python resolver for SymbolType)
_SHARED = _REPO_ROOT / "packages" / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fus():
    return _load("s2_fusion", _ANALYSIS / "fusion.py")


# --------------------------------------------------------------------------- #
# fuse_symbol_tests
# --------------------------------------------------------------------------- #
def test_runtime_and_static_union(fus):
    runtime = [("test_a", "tests/test_a.py")]
    static = [
        ("test_a", "tests/test_a.py"),          # also statically reached
        ("test_b", "tests/test_b.py"),          # static only
    ]
    fused = fus.fuse_symbol_tests(runtime, static, "thing", "pkg/a.py")
    by_key = {(c.test_file, c.test_name): c for c in fused}

    assert by_key[("tests/test_a.py", "test_a")].confidence == fus.CONFIDENCE_RUNTIME
    static_only = by_key[("tests/test_b.py", "test_b")]
    assert static_only.confidence == fus.CONFIDENCE_STATIC
    assert static_only.reason == (
        "changed_symbol:thing@pkg/a.py -> static_import -> test_b"
    )
    # Union: nothing dropped.
    assert len(fused) == 2


def test_reason_path_names_changed_symbol_and_sources(fus):
    """V2: every reason is a changed-symbol -> test path, never opaque."""
    fused = fus.fuse_symbol_tests(
        [("t", "tests/t.py")], [("t", "tests/t.py")], "thing", "pkg/a.py"
    )
    # present both runtime + static: reason lists both sources.
    assert fused[0].reason == (
        "changed_symbol:thing@pkg/a.py -> runtime_evidence+static_import -> t"
    )
    runtime_only = fus.fuse_symbol_tests([("rt", "tests/rt.py")], [], "thing", "pkg/a.py")
    assert runtime_only[0].reason == (
        "changed_symbol:thing@pkg/a.py -> runtime_evidence -> rt"
    )
    for candidate in fused + runtime_only:
        assert candidate.reason.startswith("changed_symbol:")
        assert "thing" in candidate.reason and "pkg/a.py" in candidate.reason


def test_runtime_wins_over_static_confidence(fus):
    fused = fus.fuse_symbol_tests(
        [("t", "tests/t.py")], [("t", "tests/t.py")], "thing", "pkg/a.py"
    )
    assert len(fused) == 1
    assert fused[0].confidence == fus.CONFIDENCE_RUNTIME
    assert fus.SOURCE_STATIC in fused[0].sources
    assert fus.SOURCE_RUNTIME in fused[0].sources


def test_static_only_candidates_are_medium(fus):
    fused = fus.fuse_symbol_tests([], [("t", "tests/t.py")], "thing", "pkg/a.py")
    assert fused[0].confidence == "medium"
    assert "static_import" in fused[0].reason


def test_runtime_candidates_come_first(fus):
    fused = fus.fuse_symbol_tests(
        [("rt", "tests/rt.py")], [("st", "tests/st.py")], "thing", "pkg/a.py"
    )
    assert [c.test_name for c in fused] == ["rt", "st"]


def test_helpers(fus):
    fused = fus.fuse_symbol_tests(
        [("rt", "tests/rt.py")], [("st", "tests/st.py")], "thing", "pkg/a.py"
    )
    assert fus.has_static_only(fused) is True
    assert fus.static_only_count(fused) == 1
    only_runtime = fus.fuse_symbol_tests([("rt", "tests/rt.py")], [], "thing", "pkg/a.py")
    assert fus.has_static_only(only_runtime) is False
    assert fus.static_only_count(only_runtime) == 0


def test_candidate_to_dict_shape(fus):
    fused = fus.fuse_symbol_tests([], [("st", "tests/st.py")], "thing", "pkg/a.py")
    d = fused[0].to_dict()
    assert set(d) == {"test_name", "test_file", "confidence", "reason"}


# --------------------------------------------------------------------------- #
# GraphIngestor: test files emit import edges only
# --------------------------------------------------------------------------- #
def _write(root: Path, rel: str, content: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


@pytest.fixture()
def repo(tmp_path):
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/a.py", "def thing():\n    return 1\n")
    _write(tmp_path, "tests/__init__.py", "")
    _write(
        tmp_path,
        "tests/test_a.py",
        "from pkg.a import thing\n\ndef test_thing():\n    assert thing() == 1\n",
    )
    _write(
        tmp_path,
        "tests/test_b.py",
        "import pkg.a\n\ndef test_module():\n    assert pkg.a.thing() == 1\n",
    )
    return tmp_path


def _ensure_stub(name, attrs):
    import types as _types

    try:
        __import__(name)
    except ImportError:
        mod = _types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        sys.modules[name] = mod


def _run_ingestor(repo):
    from unittest.mock import AsyncMock, MagicMock

    core = str(_REPO_ROOT / "services" / "core")
    if core not in sys.path:
        sys.path.insert(0, core)

    _ensure_stub("neo4j", {"GraphDatabase": types.SimpleNamespace(driver=lambda *a, **k: None)})
    _ensure_stub("github", {"Github": object, "Auth": object})

    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_python")
    pytest.importorskip("tree_sitter_typescript")
    pytest.importorskip("tree_sitter_javascript")

    from testsquad_core.graph.ingestor import GraphIngestor

    neo4j = MagicMock()
    neo4j.query = MagicMock(return_value=[])
    neo4j.get_all_symbols = MagicMock(return_value=[])

    indexed_symbols, indexed_files, imports = [], [], []

    async def _symbols(pid, path, symbols, language):
        indexed_symbols.append(path)

    async def _file(pid, path, language, is_test=False):
        indexed_files.append((path, is_test))

    async def _imp(pid, frm, to):
        imports.append((frm, to))

    neo4j.aindex_file_symbols = AsyncMock(side_effect=_symbols)
    neo4j.aindex_file = AsyncMock(side_effect=_file)
    neo4j.aadd_file_import = AsyncMock(side_effect=_imp)
    neo4j.aadd_call_relationship = AsyncMock()

    ingestor = GraphIngestor(neo4j, project_id=1)

    async def _drain():
        async for _ in ingestor.ingest_repo_stream(str(repo)):
            pass

    asyncio.run(_drain())
    return indexed_symbols, indexed_files, set(imports)


def test_test_file_imports_are_indexed(repo):
    indexed_symbols, indexed_files, imports = _run_ingestor(repo)
    # Both test files reach pkg/a.py statically.
    assert ("tests/test_a.py", "pkg/a.py") in imports
    assert ("tests/test_b.py", "pkg/a.py") in imports


def test_test_files_do_not_pollute_product_symbols(repo):
    indexed_symbols, indexed_files, _imports = _run_ingestor(repo)
    assert "tests/test_a.py" not in indexed_symbols
    assert "tests/test_b.py" not in indexed_symbols
    # ...but they are indexed as File nodes marked is_test.
    marked = {path for path, is_test in indexed_files if is_test}
    assert {"tests/test_a.py", "tests/test_b.py"} <= marked
