"""
Run from the repository root:
    uv run examples/snippets/clients/task_based_tool_client.py

Prerequisites:
    The task_based_tool server must be running on http://localhost:8000
    Start it with:
        cd examples/snippets && uv run server task_based_tool streamable-http
"""

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import MCP_SESSION_ID, streamablehttp_client
from mcp.types import CallToolResult


async def main():
    async with streamablehttp_client(
        "http://localhost:3000/mcp",
        headers={MCP_SESSION_ID: "5771f709-66f5-4176-9f32-ce91e3117df2"},
        terminate_on_close=False,
    ) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            result = await session.get_task_result("736054ac-5f10-409e-a06a-526761ea827a", CallToolResult)
            print(result)


if __name__ == "__main__":
    asyncio.run(main())
