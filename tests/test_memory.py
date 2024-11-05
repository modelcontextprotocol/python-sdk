import pytest
from typing_extensions import AsyncGenerator

from mcp_python.client.session import ClientSession
from mcp_python.server import Server
from mcp_python.server.memory import (
    create_connected_server_and_client_session,
)
from mcp_python.types import (
    EmptyResult,
)


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
