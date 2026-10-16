"""Unit tests for G3: scoped import/call resolution.

Loads ``graph/import_resolver.py`` and ``graph/resolvers/python.py`` by path so
the pure resolution logic and the AST extraction can be exercised without the
``testsquad_core`` package (and its Neo4j/FastAPI deps). A small fixture repo is
materialised in ``tmp_path`` and used to validate CALLS edge targets end-to-end.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GRAPH = _REPO_ROOT / "services" / "core" / "testsquad_core" / "graph"

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
def ir():
    return _load("g3_import_resolver", _GRAPH / "import_resolver.py")


@pytest.fixture(scope="module")
def pyr():
    return _load("g3_python_resolver", _GRAPH / "resolvers" / "python.py")


def _write(root: Path, rel: str, content: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


@pytest.fixture()
def repo(tmp_path):
    _write(tmp_path, "pkg/__init__.py", "from .a import thing\n")
    _write(tmp_path, "pkg/a.py", "def thing():\n    return 1\n\ndef fetch():\n    return 2\n")
    _write(tmp_path, "pkg/b.py", "def fetch():\n    return 3\n")
    _write(tmp_path, "pkg/sub/__init__.py", "")
    _write(tmp_path, "pkg/sub/sibling.py", "def work():\n    return 1\n")
    _write(
        tmp_path,
        "pkg/sub/mod.py",
        "from . import sibling\nfrom ..a import thing\n\ndef use():\n    sibling.work()\n    thing()\n",
    )
    _write(
        tmp_path,
        "consumer.py",
        "import pkg\n"
        "from pkg import thing\n"
        "from pkg.a import fetch\n\n"
        "class C:\n"
        "    def runner(self):\n"
        "        thing()\n"
        "        fetch()\n"
        "        pkg.a.fetch()\n"
        "        self.helper()\n"
        "    def helper(self):\n"
        "        return 1\n",
    )
    _write(
        tmp_path,
        "other.py",
        "from pkg.b import fetch\n\n"
        "class D:\n"
        "    def consume(self):\n"
        "        fetch()\n",
    )
    _write(
        tmp_path,
        "free.py",
        "class Z:\n    def run(self, obj):\n        obj.mystery()\n",
    )
    _write(tmp_path, "aliases.py", "import pkg.a as pa\nfrom pkg.a import thing as t\n")
    return tmp_path


def _make_ir(ir, repo, pyr):
    parser = pyr.PythonResolver()

    def parse(rel, content):
        return parser.resolve_relationships(rel, content)[1]

    return ir.ImportResolver(str(repo), parse_imports=parse)


class TestFromVsImport:
    def test_import_pkg_targets_package_init(self, ir, pyr, repo):
        r = _make_ir(ir, repo, pyr)
        assert r.resolve_import("pkg", 0, "consumer.py") == "pkg/__init__.py"

    def test_from_pkg_import_submodule_targets_submodule(self, ir, pyr, repo):
        r = _make_ir(ir, repo, pyr)
        module_file = r.resolve_import("pkg", 0, "consumer.py")
        target, name = r.resolve_from_import(module_file, "a")
        assert (target, name) == ("pkg/a.py", "a")

    def test_bindings_distinguish_module_vs_name(self, ir, pyr, repo):
        r = _make_ir(ir, repo, pyr)
        parser = pyr.PythonResolver()
        imports = parser.resolve_relationships("consumer.py", (repo / "consumer.py").read_text())[1]
        bindings = r.build_bindings(imports)
        assert bindings["pkg"]["kind"] == "module"
        assert bindings["thing"]["kind"] == "name"
        assert bindings["fetch"]["kind"] == "name"
        assert bindings["fetch"]["module"] == "pkg.a"


class TestAliases:
    def test_module_alias_resolves_to_target_module(self, ir, pyr, repo):
        r = _make_ir(ir, repo, pyr)
        parser = pyr.PythonResolver()
        imports = parser.resolve_relationships("aliases.py", (repo / "aliases.py").read_text())[1]
        bindings = r.build_bindings(imports)
        assert bindings["pa"]["module"] == "pkg.a"
        assert r._binding_home(bindings["pa"], "aliases.py") == "pkg/a.py"
        assert bindings["t"]["orig"] == "thing"
        assert r._binding_home(bindings["t"], "aliases.py") == "pkg/a.py"

    def test_alias_call_resolves(self, ir, pyr, repo):
        r = _make_ir(ir, repo, pyr)
        parser = pyr.PythonResolver()
        imports = parser.resolve_relationships(
            "aliases.py",
            "import pkg.a as pa\nfrom pkg.a import thing as t\n",
        )[1]
        bindings = r.build_bindings(imports)
        assert r.resolve_call("aliases.py", "pa.fetch", set(), bindings) == ("pkg/a.py", "fetch")
        assert r.resolve_call("aliases.py", "t", set(), bindings) == ("pkg/a.py", "thing")


class TestReExports:
    def test_from_pkg_import_reexported_name(self, ir, pyr, repo):
        r = _make_ir(ir, repo, pyr)
        module_file = r.resolve_import("pkg", 0, "consumer.py")
        # pkg/__init__.py does `from .a import thing`
        assert r.resolve_from_import(module_file, "thing") == ("pkg/a.py", "thing")

    def test_reexport_used_by_bare_call(self, ir, pyr, repo):
        r = _make_ir(ir, repo, pyr)
        parser = pyr.PythonResolver()
        imports = parser.resolve_relationships("consumer.py", (repo / "consumer.py").read_text())[1]
        bindings = r.build_bindings(imports)
        assert r.resolve_call("consumer.py", "thing", {"C", "runner", "helper"}, bindings) == (
            "pkg/a.py",
            "thing",
        )


class TestRelativeImports:
    def test_relative_from_import(self, ir, pyr, repo):
        r = _make_ir(ir, repo, pyr)
        assert r.resolve_import("", 1, "pkg/sub/mod.py") == "pkg/sub/__init__.py"
        assert r.resolve_import("sibling", 1, "pkg/sub/mod.py") == "pkg/sub/sibling.py"
        assert r.resolve_import("a", 2, "pkg/sub/mod.py") == "pkg/a.py"

    def test_relative_calls_scoped(self, ir, pyr, repo):
        r = _make_ir(ir, repo, pyr)
        parser = pyr.PythonResolver()
        src = (repo / "pkg" / "sub" / "mod.py").read_text()
        imports = parser.resolve_relationships("pkg/sub/mod.py", src)[1]
        bindings = r.build_bindings(imports)
        assert r.resolve_call("pkg/sub/mod.py", "sibling.work", {"use"}, bindings) == (
            "pkg/sub/sibling.py",
            "work",
        )
        assert r.resolve_call("pkg/sub/mod.py", "thing", {"use"}, bindings) == (
            "pkg/a.py",
            "thing",
        )


class TestNoCrossModuleFalseCalls:
    def test_duplicate_name_resolves_to_imported_module(self, ir, pyr, repo):
        r = _make_ir(ir, repo, pyr)
        parser = pyr.PythonResolver()
        imports = parser.resolve_relationships("other.py", (repo / "other.py").read_text())[1]
        bindings = r.build_bindings(imports)
        # `fetch` is imported from pkg.b -> must NOT resolve to pkg/a.py's `fetch`
        assert r.resolve_call("other.py", "fetch", {"D", "consume"}, bindings) == (
            "pkg/b.py",
            "fetch",
        )

    def test_unresolved_bare_name_returns_none(self, ir, pyr, repo):
        r = _make_ir(ir, repo, pyr)
        assert r.resolve_call("free.py", "mystery", {"Z", "run"}, {}) is None

    def test_self_method_is_same_file(self, ir, pyr, repo):
        r = _make_ir(ir, repo, pyr)
        assert r.resolve_call("consumer.py", "self.helper", {"C", "runner", "helper"}, {}) == (
            "consumer.py",
            "helper",
        )


class TestLspFallback:
    def test_ambiguous_name_uses_lsp(self, ir, pyr, repo):
        r = _make_ir(ir, repo, pyr)
        calls = []

        def fake_lsp(from_rel, line, character):
            calls.append((from_rel, line, character))
            return ("svc/impl.py", "mystery")

        result = r.resolve_call("free.py", "obj.mystery", {"Z", "run"}, {}, lsp=fake_lsp, line=2, character=8)
        assert result == ("svc/impl.py", "mystery")
        assert calls == [("free.py", 2, 8)]

    def test_no_lsp_means_no_edge(self, ir, pyr, repo):
        r = _make_ir(ir, repo, pyr)
        assert r.resolve_call("free.py", "obj.mystery", {"Z", "run"}, {}) is None


class TestFixtureRepoEndToEnd:
    """Validate CALLS edge targets produced over the whole fixture repo."""

    def _resolve_all(self, ir, pyr, repo):
        r = _make_ir(ir, repo, pyr)
        parser = pyr.PythonResolver()
        edges = set()
        for path in sorted(repo.rglob("*.py")):
            rel = path.relative_to(repo).as_posix()
            content = path.read_text()
            symbols, imports, calls = parser.resolve_relationships(rel, content)
            bindings = r.build_bindings(imports)
            local = {s["name"] for s in symbols}
            for call in calls:
                resolved = r.resolve_call(rel, call["callee"], local, bindings)
                if resolved:
                    edges.add((call["caller"], resolved[0], resolved[1]))
        return edges

    def test_expected_edges_present(self, ir, pyr, repo):
        edges = self._resolve_all(ir, pyr, repo)
        assert ("runner", "pkg/a.py", "thing") in edges
        assert ("runner", "pkg/a.py", "fetch") in edges
        assert ("runner", "consumer.py", "helper") in edges
        assert ("consume", "pkg/b.py", "fetch") in edges
        assert ("use", "pkg/sub/sibling.py", "work") in edges
        assert ("use", "pkg/a.py", "thing") in edges

    def test_no_false_duplicate_name_edges(self, ir, pyr, repo):
        edges = self._resolve_all(ir, pyr, repo)
        # pkg/b.py's `fetch` must never be reached from consumer imports and
        # vice-versa: only explicit `from pkg.b import fetch` (other.py) does.
        fetch_targets = {to_file for _c, to_file, name in edges if name == "fetch"}
        assert fetch_targets == {"pkg/a.py", "pkg/b.py"}
        assert ("runner", "pkg/b.py", "fetch") not in edges
        assert ("consume", "pkg/a.py", "fetch") not in edges


class TestClientCallScoping:
    """The Cypher for CALLS must scope the callee to a specific file."""

    def _client(self):
        import types

        if "neo4j" not in sys.modules:
            fake = types.ModuleType("neo4j")
            fake.GraphDatabase = types.SimpleNamespace(driver=lambda *a, **k: None)
            sys.modules["neo4j"] = fake
        mod = _load("g3_client", _GRAPH / "client.py")
        client = object.__new__(mod.Neo4jClient)
        captured = {}

        async def fake_aquery(cypher, params=None):
            captured["cypher"] = cypher
            captured["params"] = params
            return []

        client.aquery = fake_aquery
        return client, captured

    def test_call_edge_scoped_to_target_file(self):
        import asyncio

        client, captured = self._client()
        asyncio.run(
            client.aadd_call_relationship(1, "consumer.py", "runner", "fetch", "pkg/a.py")
        )
        assert captured["params"]["to_file"] == "pkg/a.py"
        assert captured["params"]["to_name"] == "fetch"
        assert ":File {path: $to_file}" in captured["cypher"]

    def test_call_edge_defaults_to_same_file(self):
        import asyncio

        client, captured = self._client()
        asyncio.run(client.aadd_call_relationship(1, "consumer.py", "runner", "helper"))
        assert captured["params"]["to_file"] == "consumer.py"


class TestIngestorEndToEnd:
    """Drive GraphIngestor over the fixture repo and inspect emitted edges."""

    def _ensure_stub(self, name, attrs):
        import types

        try:
            __import__(name)
        except ImportError:
            mod = types.ModuleType(name)
            for key, value in attrs.items():
                setattr(mod, key, value)
            sys.modules[name] = mod

    def _run(self, repo):
        import types as _types
        from unittest.mock import AsyncMock, MagicMock

        # Make testsquad_core importable without an installed package.
        core = str(_REPO_ROOT / "services" / "core")
        if core not in sys.path:
            sys.path.insert(0, core)

        self._ensure_stub(
            "neo4j", {"GraphDatabase": _types.SimpleNamespace(driver=lambda *a, **k: None)}
        )
        self._ensure_stub("github", {"Github": object, "Auth": object})

        pytest.importorskip("tree_sitter")
        pytest.importorskip("tree_sitter_python")
        pytest.importorskip("tree_sitter_typescript")
        pytest.importorskip("tree_sitter_javascript")

        from testsquad_core.graph.ingestor import GraphIngestor

        neo4j = MagicMock()
        neo4j.query = MagicMock(return_value=[])
        neo4j.aindex_file_symbols = AsyncMock()
        neo4j.get_all_symbols = MagicMock(return_value=[])
        imports, calls = [], []

        async def _imp(pid, frm, to):
            imports.append((frm, to))

        async def _call(pid, frm, caller, name, to_file):
            calls.append((caller, to_file, name))

        neo4j.aadd_file_import = AsyncMock(side_effect=_imp)
        neo4j.aadd_call_relationship = AsyncMock(side_effect=_call)

        ingestor = GraphIngestor(neo4j, project_id=1)

        async def _drain():
            async for _ in ingestor.ingest_repo_stream(str(repo)):
                pass

        import asyncio

        asyncio.run(_drain())
        return set(imports), set(calls)

    def test_edges_over_fixture_repo(self, repo):
        imports, calls = self._run(repo)
        assert ("consumer.py", "pkg/a.py") in imports
        assert ("pkg/__init__.py", "pkg/a.py") in imports  # re-export from `.a`
        expected = {
            ("runner", "pkg/a.py", "thing"),
            ("runner", "pkg/a.py", "fetch"),
            ("runner", "consumer.py", "helper"),
            ("consume", "pkg/b.py", "fetch"),
        }
        assert expected <= calls
        # No cross-module false CALLS on the duplicate `fetch` name.
        assert ("runner", "pkg/b.py", "fetch") not in calls
        assert ("consume", "pkg/a.py", "fetch") not in calls


