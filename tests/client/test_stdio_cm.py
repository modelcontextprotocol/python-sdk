import pytest

from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client

MCP_SERVER = {
    "command": "tee",
}


@pytest.mark.anyio
async def test_context_manager_exiting():
    async with stdio_client(StdioServerParameters(**MCP_SERVER)) as (
        read_stream,
        write_stream,
    ):
        pass
