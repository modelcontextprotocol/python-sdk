"""Test for issue #1561: unknown methods should return METHOD_NOT_FOUND."""

import anyio
import pytest
from pydantic import BaseModel

from mcp import types
from mcp.client.session import KNOWN_SERVER_REQUEST_METHODS, ClientSession
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.message import SessionMessage
from mcp.shared.session import BaseSession, request_methods_for_union
from mcp.types import METHOD_NOT_FOUND, JSONRPCError, JSONRPCRequest, ServerCapabilities


@pytest.mark.anyio
async def test_invalid_method_returns_method_not_found() -> None:
    read_send_stream, read_receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)
    write_send_stream, write_receive_stream = anyio.create_memory_object_stream[SessionMessage](10)

    try:
        async with ServerSession(
            read_stream=read_receive_stream,
            write_stream=write_send_stream,
            init_options=InitializationOptions(
                server_name="test_server",
                server_version="1.0.0",
                capabilities=ServerCapabilities(),
            ),
        ):
            await read_send_stream.send(
                SessionMessage(
                    message=JSONRPCRequest(
                        jsonrpc="2.0",
                        id=1,
                        method="invalid/method",
                        params={},
                    )
                )
            )

            await anyio.sleep(0.1)

            response_message = write_receive_stream.receive_nowait()
            response = response_message.message

            assert isinstance(response, JSONRPCError)
            assert response.id == 1
            assert response.error.code == METHOD_NOT_FOUND
            assert response.error.message == "Method not found"
    finally:
        await read_send_stream.aclose()
        await write_send_stream.aclose()
        await read_receive_stream.aclose()
        await write_receive_stream.aclose()


class MissingDefaultMethodRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int = 1
    method: str


def test_request_methods_for_union_ignores_non_literal_defaults() -> None:
    methods = request_methods_for_union(types.ServerRequest | MissingDefaultMethodRequest)
    assert methods == KNOWN_SERVER_REQUEST_METHODS


@pytest.mark.anyio
async def test_client_session_known_request_methods_match_server_request_union() -> None:
    read_send_stream, read_receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)
    write_send_stream, write_receive_stream = anyio.create_memory_object_stream[SessionMessage](10)

    try:
        session = ClientSession(read_stream=read_receive_stream, write_stream=write_send_stream)
        assert session._known_request_methods == KNOWN_SERVER_REQUEST_METHODS
    finally:
        await read_send_stream.aclose()
        await write_send_stream.aclose()
        await read_receive_stream.aclose()
        await write_receive_stream.aclose()


class DummyBaseSession(
    BaseSession[
        types.ClientRequest,
        types.ClientNotification,
        types.ClientResult,
        types.ServerRequest,
        types.ServerNotification,
    ]
):
    @property
    def _receive_request_adapter(self):
        return types.server_request_adapter

    @property
    def _receive_notification_adapter(self):
        return types.server_notification_adapter


@pytest.mark.anyio
async def test_base_session_known_request_methods_default_to_empty() -> None:
    read_send_stream, read_receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)
    write_send_stream, write_receive_stream = anyio.create_memory_object_stream[SessionMessage](10)

    try:
        session = DummyBaseSession(read_stream=read_receive_stream, write_stream=write_send_stream)
        assert session._known_request_methods == frozenset()
        assert session._receive_request_adapter is types.server_request_adapter
        assert session._receive_notification_adapter is types.server_notification_adapter
    finally:
        await read_send_stream.aclose()
        await write_send_stream.aclose()
        await read_receive_stream.aclose()
        await write_receive_stream.aclose()
