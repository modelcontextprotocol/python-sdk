from typing import Any

import pytest

from mcp import Client, types
from mcp.server import Server
from mcp.server.context import ServerRequestContext
from mcp.types import EmptyResult, Resource


async def handle_list_resources(
    ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
) -> types.ListResourcesResult:  # pragma: no cover
    return types.ListResourcesResult(
        resources=[
            Resource(
                uri="memory://test",
                name="Test Resource",
                description="A test resource",
            )
        ]
    )


@pytest.fixture
def mcp_server() -> Server:
    return Server(name="test_server", on_list_resources=handle_list_resources)


@pytest.mark.anyio
async def test_memory_server_and_client_connection(mcp_server: Server):
    """Shows how a client and server can communicate over memory streams."""
    async with Client(mcp_server) as client:
        response = await client.send_ping()
        assert isinstance(response, EmptyResult)
