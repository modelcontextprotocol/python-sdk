import anyio
import pytest

import mcp.types as types
from mcp.shared.message import SessionMessage
from mcp.shared.session import BaseSession


async def _run_client_request(request: types.JSONRPCRequest) -> types.JSONRPCError:
    request_send, request_receive = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    response_send, response_receive = anyio.create_memory_object_stream[SessionMessage](1)

    session: BaseSession[
        types.ServerRequest,
        types.ServerNotification,
        types.ServerResult,
        types.ClientRequest,
        types.ClientNotification,
    ] = BaseSession(
        read_stream=request_receive,
        write_stream=response_send,
        receive_request_type=types.ClientRequest,
        receive_notification_type=types.ClientNotification,
    )

    response_message: SessionMessage | None = None
    try:
        async with session:
            await request_send.send(SessionMessage(message=types.JSONRPCMessage(request)))
            response_message = await response_receive.receive()
    finally:
        await request_send.aclose()
        await response_receive.aclose()

    assert response_message is not None
    assert isinstance(response_message.message.root, types.JSONRPCError)
    return response_message.message.root


async def _run_server_request(request: types.JSONRPCRequest) -> types.JSONRPCError:
    request_send, request_receive = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    response_send, response_receive = anyio.create_memory_object_stream[SessionMessage](1)

    session: BaseSession[
        types.ClientRequest,
        types.ClientNotification,
        types.ClientResult,
        types.ServerRequest,
        types.ServerNotification,
    ] = BaseSession(
        read_stream=request_receive,
        write_stream=response_send,
        receive_request_type=types.ServerRequest,
        receive_notification_type=types.ServerNotification,
    )

    response_message: SessionMessage | None = None
    try:
        async with session:
            await request_send.send(SessionMessage(message=types.JSONRPCMessage(request)))
            response_message = await response_receive.receive()
    finally:
        await request_send.aclose()
        await response_receive.aclose()

    assert response_message is not None
    assert isinstance(response_message.message.root, types.JSONRPCError)
    return response_message.message.root


@pytest.mark.anyio
async def test_client_to_server_unknown_method_returns_method_not_found() -> None:
    request = types.JSONRPCRequest(jsonrpc="2.0", id=1, method="unknown/method", params=None)

    error = await _run_client_request(request)

    assert error.error.code == types.METHOD_NOT_FOUND
    assert error.error.message == "Method not found"


@pytest.mark.anyio
async def test_client_to_server_invalid_params_returns_invalid_params() -> None:
    request = types.JSONRPCRequest(jsonrpc="2.0", id=2, method="resources/read", params={})

    error = await _run_client_request(request)

    assert error.error.code == types.INVALID_PARAMS
    assert error.error.message == "Invalid request parameters"


@pytest.mark.anyio
async def test_server_to_client_unknown_method_returns_method_not_found() -> None:
    request = types.JSONRPCRequest(jsonrpc="2.0", id=3, method="server/unknown", params=None)

    error = await _run_server_request(request)

    assert error.error.code == types.METHOD_NOT_FOUND
    assert error.error.message == "Method not found"


@pytest.mark.anyio
async def test_server_to_client_invalid_params_returns_invalid_params() -> None:
    request = types.JSONRPCRequest(jsonrpc="2.0", id=4, method="sampling/createMessage", params={})

    error = await _run_server_request(request)

    assert error.error.code == types.INVALID_PARAMS
    assert error.error.message == "Invalid request parameters"
