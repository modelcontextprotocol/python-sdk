from typing_extensions import AsyncGenerator
import anyio
from pydantic import HttpUrl
from pydantic_core import Url
import pytest

from mcp_python.client.session import ClientSession
from mcp_python.server import Server
from mcp_python.server.memory import create_client_server_memory_streams, create_connected_server_and_client_session
from mcp_python.server.session import ServerSession
from mcp_python.server.types import InitializationOptions
from mcp_python.types import (
    ClientNotification,
    EmptyResult,
    InitializedNotification,
    JSONRPCMessage,
    Resource,
    ServerCapabilities,
)


@pytest.fixture
async def client_connected_to_server(mcp_server: Server) -> AsyncGenerator[ClientSession, None]:
    print('11111')
    async with create_connected_server_and_client_session(mcp_server) as client_session:
        print('2222k')
        yield client_session
        print('33')


@pytest.mark.anyio
async def test_memory_server_and_client_connection(client_connected_to_server: ClientSession):
    """Shows how a client and server can communicate over memory streams."""
    response = await client_connected_to_server.send_ping()
    print('foo')
    assert isinstance(response, EmptyResult)
    print('bar')
