from mcp import Client
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    transport = streamable_http_client(
        "http://localhost:8000/mcp",
        max_sse_event_size=32 * 1024 * 1024,
    )
    async with Client(transport) as client:
        result = await client.list_tools()
        print([tool.name for tool in result.tools])
