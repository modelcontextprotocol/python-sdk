import pytest
from pydantic import AnyUrl
from typing_extensions import AsyncGenerator

from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.shared.memory import (
    create_connected_server_and_client_session,
)
from mcp.types import (
    EmptyResult,
    Resource,
)


@pytest.fixture
def mcp_server() -> Server:
    server = Server(name="test_server")

    @server.list_resources()
    async def handle_list_resources():
        return [
            Resource(
                uri=AnyUrl("memory://test"),
                name="Test Resource",
                description="A test resource",
            )
        ]

    return server


@pytest.fixture
async def client_connected_to_server(
    mcp_server: Server,
) -> AsyncGenerator[ClientSession, None]:
    async with create_connected_server_and_client_session(mcp_server) as client_session:
        yield client_session


@pytest.mark.anyio
async def test_memory_server_and_client_connection(
    client_connected_to_server: ClientSession,
):
    """Shows how a client and server can communicate over memory streams."""
    response = await client_connected_to_server.send_ping()
    assert isinstance(response, EmptyResult)
