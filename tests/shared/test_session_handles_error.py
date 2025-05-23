from collections.abc import AsyncGenerator

import pytest
from anyio.streams.memory import MemoryObjectSendStream

from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from mcp.shared.session import BaseSession
from mcp.types import ClientNotification, ClientRequest, JSONRPCMessage, JSONRPCRequest


@pytest.fixture
async def client_write() -> (
    AsyncGenerator[MemoryObjectSendStream[SessionMessage], None]
):
    """A stream that allows to write to a running session."""
    async with create_client_server_memory_streams() as (
        (_, client_write),
        (server_read, server_write),
    ):
        async with BaseSession(
            read_stream=server_read,
            write_stream=server_write,
            receive_request_type=ClientRequest,
            receive_notification_type=ClientNotification,
        ) as _:
            yield client_write


@pytest.mark.anyio
async def test_session_does_not_raise_error_with_bad_input(
    client_write: MemoryObjectSendStream[SessionMessage],
):
    # Given a running session

    # When the client sends a bad request to the session
    request = JSONRPCRequest(jsonrpc="2.0", id=1, method="bad_method", params=None)
    message = SessionMessage(message=JSONRPCMessage(root=request))
    await client_write.send(message)

    # Then the session can still be talked to
    await client_write.send(message)
