from typing import Any

import pytest

import mcp.types as types
from mcp import Client
from mcp.server import Server
from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext
from mcp.types import EmptyResult, Resource


@pytest.fixture
def mcp_server() -> Server:
    async def handle_list_resources(
        ctx: RequestContext[ServerSession, Any, Any],
        params: types.PaginatedRequestParams | None,
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

    return Server(name="test_server", on_list_resources=handle_list_resources)


@pytest.mark.anyio
async def test_memory_server_and_client_connection(mcp_server: Server):
    """Shows how a client and server can communicate over memory streams."""
    async with Client(mcp_server) as client:
        response = await client.send_ping()
        assert isinstance(response, EmptyResult)
