import pytest

from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.anyio
async def test_context_manager_exiting():
    async with stdio_client(StdioServerParameters(command="tee")) as (
        read_stream,
        write_stream,
    ):
        pass
