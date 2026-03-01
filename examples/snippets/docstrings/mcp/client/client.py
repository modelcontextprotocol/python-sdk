"""Companion examples for src/mcp/client/client.py docstrings."""

from __future__ import annotations

import asyncio


def Client_usage() -> None:
    # region Client_usage
    from mcp.client import Client
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("test")

    @server.tool()
    def add(a: int, b: int) -> int:
        return a + b

    async def main():
        async with Client(server) as client:
            result = await client.call_tool("add", {"a": 1, "b": 2})

    asyncio.run(main())
    # endregion Client_usage
