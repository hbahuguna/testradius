# Story 11.2: Stable Symbol Identity tests
#
# A symbol must map to exactly one ``Symbol`` node. Two methods that share a
# bare name (``ClassA.get`` and ``ClassB.get``) must not collapse into a single
# node. ``symbol_resolver`` keeps the *bare* name — disambiguation is by the
# line span, both in the resolver output and in the ``Symbol`` node identity
# written by ``neo4j_store``. Module/class qualification is applied separately
# by ``instrumentation/diff_parser`` (``qualified_name``), which is why the
# resolver deliberately returns bare names.
import importlib.util
import sys
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORE = _REPO_ROOT / "services" / "core" / "testsquad_core"
_INSTR = _CORE / "instrumentation"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def _pkg():
    if "sym_id_pkg" not in sys.modules:
        pkg = types.ModuleType("sym_id_pkg")
        pkg.__path__ = [str(_INSTR)]
        sys.modules["sym_id_pkg"] = pkg
    return "sym_id_pkg"


@pytest.fixture(scope="module")
def symbol_mod(_pkg):
    return _load(f"{_pkg}.symbol_resolver", _INSTR / "symbol_resolver.py")


@pytest.fixture(scope="module")
def nstore(_pkg, symbol_mod):
    return _load(f"{_pkg}.neo4j_store", _INSTR / "neo4j_store.py")


class FakeTxClient:
    """Fake Neo4j client that records statements and reports a stored count."""

    def __init__(self, stored=None):
        self.calls = []
        self._stored = stored

    def run_in_transaction(self, statements, verify=None):
        self.calls.append(statements)
        edges = statements[0][1]["edges"]
        stored = len(edges) if self._stored is None else self._stored
        # One result row per statement; store_mappings reads results[1] and
        # replace_mappings reads results[-1].
        results = [[{"stored": stored}] for _ in statements]
        if verify is not None:
            verify(results)
        return results


_TWO_GETS = '''
class ClassA:
    def get(self):
        return 1


class ClassB:
    def get(self):
        return 2
'''


def test_same_named_methods_are_distinct_symbols(symbol_mod, tmp_path):
    """Two ``get`` methods in one file resolve to two distinct Symbol objects."""
    f = tmp_path / "m.py"
    f.write_text(_TWO_GETS)

    syms = symbol_mod.SymbolResolver()._get_symbols(str(f))
    gets = [s for s in syms if s.name == "get"]

    assert len(gets) == 2, [s.name for s in syms]
    spans = {(s.start_line, s.end_line) for s in gets}
    assert len(spans) == 2, spans


def test_same_named_methods_produce_two_edges(nstore, symbol_mod, tmp_path):
    """The store must not collapse the two ``get`` methods into one edge."""
    f = tmp_path / "m.py"
    f.write_text(_TWO_GETS)

    gets = [s for s in symbol_mod.SymbolResolver()._get_symbols(str(f)) if s.name == "get"]
    mappings = [{
        "test_name": "test_get",
        "test_file": "tests/test_m.py",
        "symbols": gets,
    }]

    client = FakeTxClient()
    store = nstore.Neo4jStore(neo4j_client=client)

    count = store.store_mappings(mappings, project_id=1)

    assert count == 2
    edges = client.calls[0][0][1]["edges"]
    assert len(edges) == 2
    assert len({(e["start_line"], e["end_line"]) for e in edges}) == 2


def test_symbol_node_identity_includes_line_span(nstore, symbol_mod, tmp_path):
    """The Symbol MERGE key (both write paths) carries the line span."""
    f = tmp_path / "m.py"
    f.write_text(_TWO_GETS)
    gets = [s for s in symbol_mod.SymbolResolver()._get_symbols(str(f)) if s.name == "get"]
    mappings = [{"test_name": "test_get", "test_file": "tests/test_m.py", "symbols": gets}]

    for method in ("store_mappings", "replace_mappings"):
        client = FakeTxClient()
        store = nstore.Neo4jStore(neo4j_client=client)
        getattr(store, method)(mappings, project_id=1)

        cypher = "\n".join(stmt for stmt, _ in client.calls[0])
        symbol_merge = cypher.split("MERGE (s:Symbol", 1)[1]
        assert "start_line" in symbol_merge
        assert "end_line" in symbol_merge
