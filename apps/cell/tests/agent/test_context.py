from __future__ import annotations

import asyncio

from cell.agent.context import ContextNode, StaticContextClient, WorkspaceContextClient


def test_workspace_context_has_stable_ids_and_symbols(tmp_path):
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "index.html").write_text("<button id='x'>Save</button>")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "client.ts").write_text(
        "export function loadProducts() { return 1; }\nconst handler = () => 2;\n"
    )

    async def scenario():
        client = WorkspaceContextClient(tmp_path)
        nodes = await client.retrieve("loadProducts index")
        ids = {node.node_id for node in nodes}
        assert "file:public/index.html" in ids
        assert "symbol:src/client.ts:loadProducts" in ids
        assert await client.get("file:public/index.html") is not None
        assert await client.get("file:missing") is None

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
