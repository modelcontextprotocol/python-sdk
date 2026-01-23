import pytest

from mcp import Client
from mcp.client.session import ClientSession
from mcp.client.transport_session import ClientTransportSession
from mcp.server import Server
from mcp.types import EmptyResult, Resource


@pytest.fixture
def mcp_server() -> Server:
    server = Server(name="test_server")

    @server.list_resources()
    async def handle_list_resources():  # pragma: no cover
        return [
            Resource(
                uri="memory://test",
                name="Test Resource",
                description="A test resource",
            )
        ]

    return server


@pytest.mark.anyio
async def test_memory_server_and_client_connection(mcp_server: Server):
    """Shows how a client and server can communicate over memory streams."""
    async with Client(mcp_server) as client:
        response = await client.send_ping()
        assert isinstance(response, EmptyResult)
