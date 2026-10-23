from __future__ import annotations

import asyncio

from cell.agent.context import (
    ContextNode,
    ContextUnavailable,
    FallbackContextClient,
    StaticContextClient,
    WorkspaceContextClient,
    context_metadata,
)


def test_workspace_context_has_stable_ids_routes_tests_and_cache(tmp_path):
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "index.html").write_text("<button id='x'>Save</button>")
    (tmp_path / "public" / "cart.html").write_text("<p>Your cart is empty.</p>")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "client.ts").write_text(
        "export function loadProducts() { return 1; }\nconst handler = () => 2;\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "checkout.spec.ts").write_text("test('checkout', () => {});")

    async def scenario():
        client = WorkspaceContextClient(tmp_path)
        nodes = await client.retrieve("loadProducts index")
        ids = {node.node_id for node in nodes}
        assert "file:public/index.html" in ids
        assert "symbol:src/client.ts:loadProducts" in ids
        assert "route:/" in ids
        assert "route:/cart" in ids
        assert "test:tests/checkout.spec.ts" in ids
        assert await client.get("file:public/index.html") is not None
        assert await client.get("file:missing") is None
        assert client.cache_hits > 0
        assert client.cache_misses > 0

    asyncio.run(scenario())


def test_static_context_returns_ranked_nodes():
    nodes = [
        ContextNode("file:a", "file", "a", "checkout page", "checkout"),
        ContextNode("file:b", "file", "b", "cart page", "cart"),
    ]

    async def scenario():
        client = StaticContextClient(nodes)
        result = await client.retrieve("checkout")
        assert result[0].node_id == "file:a"

    asyncio.run(scenario())


def test_context_budget_truncates_and_reports_the_node(tmp_path):
    (tmp_path / "index.html").write_text("x" * 5000)

    async def scenario():
        client = WorkspaceContextClient(tmp_path, token_budget=40)
        nodes = await client.retrieve("index", limit=1)
        assert nodes
        assert nodes[0].metadata["truncated"] is True
        assert client.truncated_nodes == 1
        assert client.last_budget_used == 40

    asyncio.run(scenario())


def test_graph_failure_falls_back_and_marks_the_source():
    class DownGraph:
        source = "graph"

        async def retrieve(self, query, *, limit=12):
            raise ContextUnavailable("connection refused")

        async def get(self, node_id):
            raise AssertionError("fallback citations must not use the down graph")

    node = ContextNode("file:public/index.html", "file", "public/index.html", "index")
    fallback = StaticContextClient([node])

    async def scenario():
        client = FallbackContextClient(DownGraph(), fallback)
        nodes = await client.retrieve("index")
        assert [item.node_id for item in nodes] == ["file:public/index.html"]
        assert client.source == "static"
        assert client.fallback_used is True
        assert client.fallback_reason == "connection refused"
        assert await client.get("file:public/index.html") is not None
        metadata = context_metadata(client)
        assert metadata["source"] == "static"
        assert metadata["fallback_used"] is True

    asyncio.run(scenario())
