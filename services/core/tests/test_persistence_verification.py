"""Unit tests for D1: transactional + verified persistence.

Covers two layers, both loaded by file path so the tests run without the
FastAPI/Neo4j runtime dependencies:

* ``instrumentation/neo4j_store.py`` — mappings are written and the stored
  EVIDENCE count is re-counted; a write failure or count mismatch raises
  ``PersistenceError`` instead of silently returning 0 (the project-5 bug).
* ``graph/client.py`` — ``run_in_transaction`` commits all statements or rolls
  the whole transaction back when a statement (or the verification callback)
  fails.
"""
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
def symbol_mod():
    """Load symbol_resolver under a synthetic package."""
    if "d1_instr" not in sys.modules:
        pkg = types.ModuleType("d1_instr")
        pkg.__path__ = [str(_INSTR)]
        sys.modules["d1_instr"] = pkg
    return _load("d1_instr.symbol_resolver", _INSTR / "symbol_resolver.py")


@pytest.fixture(scope="module")
def nstore(symbol_mod):
    """Load neo4j_store (its relative import resolves via the package)."""
    return _load("d1_instr.neo4j_store", _INSTR / "neo4j_store.py")


@pytest.fixture(scope="module")
def client_mod():
    """Load graph.client with a stub neo4j module (no driver needed)."""
    fake = types.ModuleType("neo4j")
    fake.GraphDatabase = types.SimpleNamespace(driver=lambda *a, **k: None)
    sys.modules["neo4j"] = fake
    return _load("d1_client", _CORE / "graph" / "client.py")


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeTxClient:
    """Fake Neo4j client recording ``run_in_transaction`` calls."""

    def __init__(self, stored=None, write_error=None):
        self.calls = []
        self.committed = False
        self.rolled_back = False
        self._stored = stored
        self._write_error = write_error

    def run_in_transaction(self, statements, verify=None):
        self.calls.append(statements)
        if self._write_error:
            self.rolled_back = True
            raise self._write_error
        edges = statements[0][1]["edges"]
        results = [[{"created": len(edges)}], [{"stored": self._stored}]]
        try:
            if verify is not None:
                verify(results)
        except Exception:
            self.rolled_back = True
            raise
        self.committed = True
        return results


def _mapping(symbol_mod, test_name="test_add", test_file="tests/test_math.py",
             symbol_name="add", symbol_file="src/math.py"):
    return {
        "test_name": test_name,
        "test_file": test_file,
        "symbols": [
            symbol_mod.Symbol(name=symbol_name, symbol_type="function",
                              file_path=symbol_file, start_line=1, end_line=10)
        ],
    }


# --------------------------------------------------------------------------- #
# Neo4jStore.store_mappings — verified persistence
# --------------------------------------------------------------------------- #
def test_success_returns_verified_count(nstore, symbol_mod):
    client = FakeTxClient(stored=1)
    store = nstore.Neo4jStore(neo4j_client=client)

    count = store.store_mappings([_mapping(symbol_mod)], project_id=7)

    assert count == 1
    assert client.committed
    assert not client.rolled_back


def test_count_mismatch_raises_and_rolls_back(nstore, symbol_mod):
    client = FakeTxClient(stored=0)
    store = nstore.Neo4jStore(neo4j_client=client)

    with pytest.raises(nstore.PersistenceError):
        store.store_mappings([_mapping(symbol_mod)], project_id=7)

    assert client.rolled_back
    assert not client.committed


def test_write_failure_raises_not_silent_zero(nstore, symbol_mod):
    """Project-5 regression: a swallowed write failure must raise, not return 0."""
    client = FakeTxClient(write_error=RuntimeError("unknown property"))
    store = nstore.Neo4jStore(neo4j_client=client)

    with pytest.raises(nstore.PersistenceError):
        store.store_mappings([_mapping(symbol_mod)], project_id=7)

    assert client.rolled_back
    assert not client.committed


def test_duplicate_edges_are_deduped(nstore, symbol_mod):
    client = FakeTxClient(stored=1)
    store = nstore.Neo4jStore(neo4j_client=client)

    dup = [_mapping(symbol_mod), _mapping(symbol_mod)]
    count = store.store_mappings(dup, project_id=7)

    assert count == 1
    edges = client.calls[0][0][1]["edges"]
    assert len(edges) == 1


def test_no_symbols_yields_zero_without_transaction(nstore):
    client = FakeTxClient(stored=0)
    store = nstore.Neo4jStore(neo4j_client=client)

    mappings = [{"test_name": "t", "test_file": "f.py", "symbols": []}]
    assert store.store_mappings(mappings, project_id=7) == 0
    assert client.calls == []


def test_empty_mappings_and_no_client(nstore, symbol_mod):
    store = nstore.Neo4jStore(neo4j_client=FakeTxClient())
    assert store.store_mappings([], project_id=7) == 0
    assert nstore.Neo4jStore(neo4j_client=None).store_mappings([_mapping(symbol_mod)], project_id=7) == 0


def test_write_query_keeps_evidence_contract(nstore, symbol_mod):
    client = FakeTxClient(stored=1)
    store = nstore.Neo4jStore(neo4j_client=client)

    store.store_mappings([_mapping(symbol_mod)], project_id=7)

    write_query = client.calls[0][0][0]
    verify_query = client.calls[0][1][0]
    assert "EVIDENCE" in write_query
    assert "source: 'coverage'" in write_query
    # Story 11.7: confidence lives in SET, not the MERGE key, so re-runs
    # update it instead of keeping the first value (or writing a 2nd edge).
    assert "confidence: 1.0" not in write_query
    assert "SET ev.confidence = e.confidence" in write_query
    assert "count(ev)" in verify_query


def test_coverage_metadata_round_trips(nstore, symbol_mod):
    """Story 11.7: covered_line_count / coverage_kind / confidence persist."""
    client = FakeTxClient(stored=1)
    store = nstore.Neo4jStore(neo4j_client=client)

    mapping = _mapping(symbol_mod)
    mapping["symbols"] = [
        symbol_mod.Symbol(
            name="add", symbol_type="function", file_path="src/math.py",
            start_line=1, end_line=10, covered_line_count=3,
            coverage_kind="line",
        )
    ]
    store.store_mappings([mapping], project_id=7)

    edge = client.calls[0][0][1]["edges"][0]
    assert edge["covered_line_count"] == 3
    assert edge["coverage_kind"] == "line"
    assert edge["confidence"] == pytest.approx(0.3)


def test_inferred_attribution_round_trips_at_half_weight(nstore, symbol_mod):
    """A class-span attribution stores kind 'inferred' and half confidence."""
    client = FakeTxClient(stored=1)
    store = nstore.Neo4jStore(neo4j_client=client)

    mapping = _mapping(symbol_mod, symbol_name="Calc")
    mapping["symbols"] = [
        symbol_mod.Symbol(
            name="Calc", symbol_type="class", file_path="src/math.py",
            start_line=1, end_line=10, covered_line_count=5,
            coverage_kind="inferred",
        )
    ]
    store.store_mappings([mapping], project_id=7)

    edge = client.calls[0][0][1]["edges"][0]
    assert edge["coverage_kind"] == "inferred"
    assert edge["confidence"] == pytest.approx(0.25)


# --------------------------------------------------------------------------- #
# Neo4jStore.replace_mappings — atomic evidence replacement (D2 freshness)
# --------------------------------------------------------------------------- #
def test_replace_mappings_returns_verified_count(nstore, symbol_mod):
    client = FakeTxClient(stored=1)
    store = nstore.Neo4jStore(neo4j_client=client)

    count = store.replace_mappings([_mapping(symbol_mod)], project_id=7, built_at_sha="a" * 40)

    assert count == 1
    assert client.committed
    assert not client.rolled_back


def test_replace_mappings_deletes_coverage_edges_before_write(nstore, symbol_mod):
    """Prior coverage EVIDENCE edges are removed in the same transaction as the write."""
    client = FakeTxClient(stored=1)
    store = nstore.Neo4jStore(neo4j_client=client)

    store.replace_mappings([_mapping(symbol_mod)], project_id=7, built_at_sha="a" * 40)

    statements = client.calls[0]
    # The replacement deletes prior coverage evidence before re-writing it...
    assert "DELETE" in statements[0][0].upper()
    assert "EVIDENCE" in statements[0][0]
    # ...and the write/verify still match the established contract.
    write_query = statements[-2][0]
    verify_query = statements[-1][0]
    assert "source: 'coverage'" in write_query
    assert "count(ev)" in verify_query


def test_replace_mappings_clears_stale_stamps_before_write(nstore, symbol_mod):
    """Surviving TestSymbols lose their old built_at_sha so exactly one SHA remains."""
    client = FakeTxClient(stored=1)
    store = nstore.Neo4jStore(neo4j_client=client)

    store.replace_mappings([_mapping(symbol_mod)], project_id=7, built_at_sha="b" * 40)

    statements = client.calls[0]
    clear_query = statements[1][0]
    assert "TestSymbol" in clear_query
    assert "built_at_sha" in clear_query
    assert "null" in clear_query.lower()
    # Clear-stamps must run before the write that re-stamps the current run.
    assert "built_at_sha" not in statements[0][0]


def test_replace_mappings_does_not_touch_non_coverage_edges(nstore, symbol_mod):
    """The delete is scoped to coverage-sourced edges only (LLM/approved edges survive)."""
    client = FakeTxClient(stored=1)
    store = nstore.Neo4jStore(neo4j_client=client)

    store.replace_mappings([_mapping(symbol_mod)], project_id=7, built_at_sha="c" * 40)

    delete_query = client.calls[0][0][0]
    assert "source" in delete_query
    assert "coverage" in delete_query


def test_replace_mappings_passes_built_at_sha_param(nstore, symbol_mod):
    client = FakeTxClient(stored=1)
    store = nstore.Neo4jStore(neo4j_client=client)

    store.replace_mappings([_mapping(symbol_mod)], project_id=7, built_at_sha="d" * 40)

    write_params = client.calls[0][-2][1]
    assert write_params["built_at_sha"] == "d" * 40
    assert write_params["project_id"] == 7


def test_replace_mappings_count_mismatch_raises_and_rolls_back(nstore, symbol_mod):
    client = FakeTxClient(stored=0)
    store = nstore.Neo4jStore(neo4j_client=client)

    with pytest.raises(nstore.PersistenceError):
        store.replace_mappings([_mapping(symbol_mod)], project_id=7)

    assert client.rolled_back
    assert not client.committed


def test_replace_mappings_empty_or_no_client(nstore, symbol_mod):
    store = nstore.Neo4jStore(neo4j_client=FakeTxClient())
    assert store.replace_mappings([], project_id=7) == 0
    assert nstore.Neo4jStore(neo4j_client=None).replace_mappings(
        [_mapping(symbol_mod)], project_id=7
    ) == 0


# --------------------------------------------------------------------------- #
# Neo4jClient.run_in_transaction
# --------------------------------------------------------------------------- #
class FakeRecord:
    def __init__(self, data):
        self._data = data

    def data(self):
        return self._data


class FakeTx:
    def __init__(self, fail_on=None):
        self.committed = False
        self.rolled_back = False
        self._fail_on = fail_on

    def run(self, cypher, params=None):
        if self._fail_on and self._fail_on in cypher:
            raise RuntimeError("statement failed")
        return [FakeRecord({"ok": True})]

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class FakeSession:
    def __init__(self, tx):
        self._tx = tx

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def begin_transaction(self):
        return self._tx


class FakeDriver:
    def __init__(self, tx):
        self._tx = tx

    def session(self):
        return FakeSession(self._tx)


def _client(client_mod, tx):
    c = client_mod.Neo4jClient.__new__(client_mod.Neo4jClient)
    c.driver = FakeDriver(tx)
    return c


def test_run_in_transaction_commits_and_returns_results(client_mod):
    tx = FakeTx()
    results = _client(client_mod, tx).run_in_transaction([("RETURN 1", {}), ("RETURN 2", {})])

    assert tx.committed
    assert not tx.rolled_back
    assert len(results) == 2
    assert results[0][0]["ok"] is True


def test_run_in_transaction_rolls_back_on_statement_error(client_mod):
    tx = FakeTx(fail_on="BOOM")
    with pytest.raises(RuntimeError):
        _client(client_mod, tx).run_in_transaction([("BOOM", {})])

    assert tx.rolled_back
    assert not tx.committed


def test_run_in_transaction_rolls_back_when_verify_fails(client_mod):
    tx = FakeTx()

    def verify(_results):
        raise ValueError("mismatch")

    with pytest.raises(ValueError):
        _client(client_mod, tx).run_in_transaction([("RETURN 1", {})], verify=verify)

    assert tx.rolled_back
    assert not tx.committed
