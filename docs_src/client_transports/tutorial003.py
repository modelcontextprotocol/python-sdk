import httpx

from mcp import Client, create_mcp_http_client
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    async with create_mcp_http_client(
        headers={"Authorization": "Bearer ..."},
        timeout=httpx.Timeout(30.0, read=300.0),
    ) as http_client:
        transport = streamable_http_client("http://localhost:8000/mcp", http_client=http_client)
        async with Client(transport) as client:
            result = await client.list_tools()
            print([tool.name for tool in result.tools])
