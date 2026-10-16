"""Story 11.7: confidence gradation + coverage metadata on EVIDENCE edges.

Pure logic — no Neo4j/FastAPI runtime is imported. ``attribution`` and
``confidence`` are loaded under a synthetic package (so ``neo4j_store``'s
relative imports resolve), the same isolation trick used by the other
path-loaded instrumentation tests.
"""
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORE = _REPO_ROOT / "services" / "core" / "testsquad_core"
_INSTR = _CORE / "instrumentation"
_PKG = "conf_pkg"


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
    attribution = _load(f"{_PKG}.attribution", _INSTR / "attribution.py")
    confidence = _load(f"{_PKG}.confidence", _INSTR / "confidence.py")
    symbol = _load(f"{_PKG}.symbol_resolver", _INSTR / "symbol_resolver.py")
    nstore = _load(f"{_PKG}.neo4j_store", _INSTR / "neo4j_store.py")
    return types.SimpleNamespace(
        attribution=attribution,
        confidence=confidence,
        symbol=symbol,
        nstore=nstore,
    )


# --------------------------------------------------------------------------- #
# The documented formula
# --------------------------------------------------------------------------- #
class TestConfidenceFormula:
    def test_fully_covered_symbol_is_fully_confident(self, mods):
        c = mods.confidence
        assert c.confidence_for(4, 1, 4, c.LINE) == 1.0

    def test_partial_coverage_lowers_confidence(self, mods):
        c = mods.confidence
        assert c.confidence_for(3, 1, 10, c.LINE) == pytest.approx(0.3)
        assert c.confidence_for(3, 1, 10, c.LINE) < 1.0

    def test_inferred_attribution_is_penalized(self, mods):
        c = mods.confidence
        direct = c.confidence_for(4, 1, 4, c.LINE)
        inferred = c.confidence_for(4, 1, 4, c.INFERRED)
        assert inferred == pytest.approx(direct * c.INFERRED_WEIGHT)
        assert inferred < direct

    def test_legacy_missing_count_keeps_full_confidence(self, mods):
        c = mods.confidence
        assert c.confidence_for(None, 1, 10, c.LINE) == 1.0

    def test_count_is_clamped_to_the_span(self, mods):
        c = mods.confidence
        assert c.confidence_for(99, 1, 5, c.LINE) == 1.0
        assert c.confidence_for(-1, 1, 5, c.LINE) == 0.0

    def test_kind_for_symbol(self, mods):
        a = mods.attribution
        assert a.symbol_identity is not None  # exported for the resolvers
        c = mods.confidence
        assert c.kind_for_symbol("class") == c.INFERRED
        assert c.kind_for_symbol("function") == c.LINE
        assert c.kind_for_symbol("method") == c.LINE
        assert c.kind_for_symbol("async_function") == c.LINE


# --------------------------------------------------------------------------- #
# Attribution counts per symbol
# --------------------------------------------------------------------------- #
class TestAttributionCounts:
    def test_counts_covered_lines_per_owner(self, mods, tmp_path):
        f = tmp_path / "m.py"
        f.write_text("def add(a, b):\n    x = a + b\n    return x\n")

        r = mods.symbol.SymbolResolver()
        syms = r.resolve_symbols(str(f), {"t": [1, 2, 3]})

        assert [s.name for s in syms] == ["add"]
        assert syms[0].covered_line_count == 3
        assert syms[0].coverage_kind == "line"

    def test_class_attribution_is_inferred(self, mods, tmp_path):
        f = tmp_path / "m.py"
        f.write_text(
            "class C:\n"          # 1
            "    x = 1\n"          # 2  <- class body, outside every method
            "    def m(self):\n"   # 3
            "        return self.x\n"  # 4
        )

        r = mods.symbol.SymbolResolver()
        syms = r.resolve_symbols(str(f), {"t": [2]})

        assert [s.name for s in syms] == ["C"]
        assert syms[0].coverage_kind == "inferred"
        assert syms[0].covered_line_count == 1

    def test_method_attribution_is_line_and_counts_partial(self, mods, tmp_path):
        f = tmp_path / "m.py"
        f.write_text(
            "class C:\n"                   # 1
            "    def m(self):\n"           # 2
            "        a = 1\n"              # 3
            "        b = 2\n"              # 4
            "        return a + b\n"        # 5
        )

        r = mods.symbol.SymbolResolver()
        syms = r.resolve_symbols(str(f), {"t": [2, 3]})

        assert [s.name for s in syms] == ["m"]
        # 2 of the method's 4-line span -> 0.5
        assert syms[0].covered_line_count == 2
        assert syms[0].coverage_kind == "line"

    def test_resolve_symbols_does_not_mutate_the_symbol_cache(self, mods, tmp_path):
        f = tmp_path / "m.py"
        f.write_text("def add(a, b):\n    return a + b\n")

        r = mods.symbol.SymbolResolver()
        r.resolve_symbols(str(f), {"t": [1, 2]})

        # A second resolution with less coverage must not see the first count.
        syms = r.resolve_symbols(str(f), {"t": [1]})
        assert syms[0].covered_line_count == 1

    def test_attribution_counts_never_reach_the_parser_cache(self, mods):
        a = mods.attribution

        class S:
            def __init__(self, name, t, s, e):
                self.name, self.symbol_type = name, t
                self.start_line, self.end_line = s, e

        counts = a.attributed_line_counts(
            [S("inner", "method", 2, 3), S("Outer", "class", 1, 10)],
            {"t": [1, 2, 3]},
        )
        # Lines 2-3 credit the inner method; line 1 (class body) credits the class.
        assert counts[a.symbol_identity(S("inner", "method", 2, 3))] == 2
        assert counts[a.symbol_identity(S("Outer", "class", 1, 10))] == 1


# --------------------------------------------------------------------------- #
# _build_edges threads metadata into the edge dicts
# --------------------------------------------------------------------------- #
class TestBuildEdgesMetadata:
    def _edges(self, mods, symbols):
        store = mods.nstore.Neo4jStore(neo4j_client=None)
        return store._build_edges([{
            "test_name": "t", "test_file": "tests/t.py", "symbols": symbols,
        }])

    def test_partially_covered_symbol_edge_is_less_than_one(self, mods):
        S = mods.symbol.Symbol
        edges = self._edges(mods, [
            S(name="big", symbol_type="function", file_path="src/a.py",
              start_line=1, end_line=10, covered_line_count=2,
              coverage_kind="line"),
        ])
        assert edges[0]["covered_line_count"] == 2
        assert edges[0]["coverage_kind"] == "line"
        assert edges[0]["confidence"] == pytest.approx(0.2)

    def test_fully_covered_symbol_edge_is_fully_confident(self, mods):
        S = mods.symbol.Symbol
        edges = self._edges(mods, [
            S(name="small", symbol_type="function", file_path="src/a.py",
              start_line=1, end_line=2, covered_line_count=2,
              coverage_kind="line"),
        ])
        assert edges[0]["confidence"] == 1.0

    def test_inferred_edge_is_penalized(self, mods):
        S = mods.symbol.Symbol
        edges = self._edges(mods, [
            S(name="C", symbol_type="class", file_path="src/a.py",
              start_line=1, end_line=2, covered_line_count=2,
              coverage_kind="inferred"),
        ])
        assert edges[0]["coverage_kind"] == "inferred"
        assert edges[0]["confidence"] == pytest.approx(0.5)

    def test_seven_element_tuple_carries_the_metadata(self, mods):
        edges = self._edges(mods, [("f", "function", 1, 10, "src/a.py", 5, "line")])
        assert edges[0]["covered_line_count"] == 5
        assert edges[0]["coverage_kind"] == "line"
        assert edges[0]["confidence"] == pytest.approx(0.5)

    def test_legacy_five_element_tuple_keeps_full_confidence(self, mods):
        edges = self._edges(mods, [("f", "function", 1, 10, "src/a.py")])
        assert edges[0]["confidence"] == 1.0

    def test_legacy_class_tuple_infers_the_kind(self, mods):
        edges = self._edges(mods, [("C", "class", 1, 10, "src/a.py")])
        assert edges[0]["coverage_kind"] == "inferred"
        assert edges[0]["confidence"] == pytest.approx(0.5)

    def test_metadata_is_not_part_of_the_edge_identity(self, mods):
        store = mods.nstore.Neo4jStore(neo4j_client=None)
        edges = store._build_edges([
            {"test_name": "t", "test_file": "tests/t.py",
             "symbols": [("f", "function", 1, 10, "src/a.py", 2, "line")]},
            {"test_name": "t", "test_file": "tests/t.py",
             "symbols": [("f", "function", 1, 10, "src/a.py", 9, "line")]},
        ])
        assert len(store._distinct_edges(edges)) == 1


# --------------------------------------------------------------------------- #
# The write queries update confidence/metadata instead of pinning it
# --------------------------------------------------------------------------- #
class TestWriteQueryContract:
    def _client(self):
        client = MagicMock()
        client.run_in_transaction.return_value = [[{"stored": 1}]] * 6
        return client

    def test_store_mappings_sets_confidence_on_match(self, mods):
        S = mods.symbol.Symbol
        client = self._client()
        store = mods.nstore.Neo4jStore(neo4j_client=client)
        store.store_mappings([{
            "test_name": "t", "test_file": "tests/t.py",
            "symbols": [S(name="f", symbol_type="function", file_path="a.py",
                         start_line=1, end_line=10, covered_line_count=3,
                         coverage_kind="line")],
        }], project_id=1)

        write_query = client.run_in_transaction.call_args[0][0][0][0]
        # Merge on source only — a re-run with different confidence must update
        # the same edge, not create a second one pinned to the first value.
        assert "confidence: 1.0" not in write_query
        assert "SET ev.confidence = e.confidence" in write_query
        assert "ev.covered_line_count = e.covered_line_count" in write_query
        assert "ev.coverage_kind = e.coverage_kind" in write_query

    def test_replace_mappings_sets_confidence_on_match(self, mods):
        S = mods.symbol.Symbol
        client = self._client()
        store = mods.nstore.Neo4jStore(neo4j_client=client)
        store.replace_mappings([{
            "test_name": "t", "test_file": "tests/t.py",
            "symbols": [S(name="f", symbol_type="function", file_path="a.py",
                         start_line=1, end_line=10, covered_line_count=3,
                         coverage_kind="line")],
        }], project_id=1, built_at_sha="a" * 40)

        statements = client.run_in_transaction.call_args[0][0]
        write_query = next(
            q for q, _ in statements if "MERGE (t)-[ev:EVIDENCE" in q
        )
        assert "confidence: 1.0" not in write_query
        assert "SET ev.confidence = e.confidence" in write_query
        assert "ev.covered_line_count = e.covered_line_count" in write_query
        assert "ev.coverage_kind = e.coverage_kind" in write_query

    def test_incremental_mappings_set_confidence_on_match(self, mods):
        S = mods.symbol.Symbol
        client = self._client()
        store = mods.nstore.Neo4jStore(neo4j_client=client)
        store.apply_incremental_mappings(
            [{
                "test_name": "t", "test_file": "tests/t.py",
                "symbols": [S(name="f", symbol_type="function", file_path="a.py",
                              start_line=1, end_line=10, covered_line_count=3,
                              coverage_kind="line")],
            }],
            project_id=1, built_at_sha="a" * 40, rerun_test_names=["t"],
        )

        statements = client.run_in_transaction.call_args[0][0]
        write_query = next(
            q for q, _ in statements if "MERGE (t)-[ev:EVIDENCE" in q
        )
        assert "confidence: 1.0" not in write_query
        assert "SET ev.confidence = e.confidence" in write_query
        assert "ev.covered_line_count = e.covered_line_count" in write_query
        assert "ev.coverage_kind = e.coverage_kind" in write_query

    def test_rerun_passes_the_new_confidence_as_a_parameter(self, mods):
        """Re-runs must send fresh confidence, not the first run's value."""
        S = mods.symbol.Symbol
        client = self._client()
        store = mods.nstore.Neo4jStore(neo4j_client=client)

        store.store_mappings([{
            "test_name": "t", "test_file": "tests/t.py",
            "symbols": [S(name="f", symbol_type="function", file_path="a.py",
                          start_line=1, end_line=10, covered_line_count=2,
                          coverage_kind="line")],
        }], project_id=1)
        edges_v1 = client.run_in_transaction.call_args[0][0][0][1]["edges"]
        assert edges_v1[0]["confidence"] == pytest.approx(0.2)

        # A re-run exercising more of the symbol yields a higher confidence.
        store.store_mappings([{
            "test_name": "t", "test_file": "tests/t.py",
            "symbols": [S(name="f", symbol_type="function", file_path="a.py",
                          start_line=1, end_line=10, covered_line_count=9,
                          coverage_kind="line")],
        }], project_id=1)
        edges_v2 = client.run_in_transaction.call_args[0][0][0][1]["edges"]
        assert edges_v2[0]["confidence"] == pytest.approx(0.9)

    def test_get_impacted_tests_returns_metadata_and_orders_by_confidence(self, mods):
        client = MagicMock()
        client.query.return_value = [
            {"test_name": "t_full", "test_file": "tests/a.py", "confidence": 1.0,
             "source": "coverage", "covered_line_count": 10, "coverage_kind": "line"},
            {"test_name": "t_part", "test_file": "tests/a.py", "confidence": 0.3,
             "source": "coverage", "covered_line_count": 3, "coverage_kind": "line"},
        ]
        store = mods.nstore.Neo4jStore(neo4j_client=client)
        impacted = store.get_impacted_tests(project_id=1, changed_symbols=["f"])

        assert [t["test_name"] for t in impacted] == ["t_full", "t_part"]
        assert impacted[0]["covered_line_count"] == 10
        assert impacted[0]["coverage_kind"] == "line"
        query = client.query.call_args_list[0][0][0]
        assert "e.covered_line_count" in query
        assert "e.coverage_kind" in query
        assert "ORDER BY confidence DESC" in query


# --------------------------------------------------------------------------- #
# TIA calibration consumes the edge confidence (AC4)
# --------------------------------------------------------------------------- #
class TestCoverageCalibration:
    def test_calibrator_uses_the_edge_confidence(self):
        from testsquad_core.analysis.calibrators import get_calibrator

        fn = get_calibrator("coverage")
        # A fully-evidenced edge keeps the historical near-certainty...
        assert fn(1.0) == pytest.approx(0.99, abs=0.001)
        # ...a weak one is pulled toward the floor instead of faking 0.99.
        assert fn(0.0) == pytest.approx(0.5, abs=0.001)
        assert fn(0.5) < fn(1.0)
        assert fn(0.5) > fn(0.0)

    def test_calibrator_survives_a_null_confidence(self):
        from testsquad_core.analysis.calibrators import get_calibrator

        fn = get_calibrator("coverage")
        assert 0.5 <= fn(None) <= 0.99  # legacy edge, assumed full confidence
