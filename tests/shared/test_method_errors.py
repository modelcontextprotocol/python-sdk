from typing import cast

import anyio
import pytest

import mcp.types as types
from mcp.shared.message import SessionMessage
from mcp.shared.session import BaseSession


def _ensure(condition: bool, message: str) -> None:
    if condition:
        return
    pytest.fail(message)  # pragma: no cover


def _assert_error(error: types.JSONRPCError, expected_code: int, expected_message: str) -> None:
    error_payload = error.error
    _ensure(error_payload.code == expected_code, f"expected {expected_code}, got {error_payload.code}")
    _ensure(error_payload.message == expected_message, f"unexpected error message: {error_payload.message}")


async def _run_client_request(request: types.JSONRPCRequest) -> types.JSONRPCError:
    request_send, request_receive = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    response_send, response_receive = anyio.create_memory_object_stream[SessionMessage](1)

    async with request_send, request_receive, response_send, response_receive:
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

        async with session:
            await request_send.send(SessionMessage(message=types.JSONRPCMessage(request)))
            response_message = await response_receive.receive()

            root = response_message.message.root
            _ensure(isinstance(root, types.JSONRPCError), "expected a JSON-RPC error response")
            return cast(types.JSONRPCError, root)


async def _run_server_request(request: types.JSONRPCRequest) -> types.JSONRPCError:
    request_send, request_receive = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    response_send, response_receive = anyio.create_memory_object_stream[SessionMessage](1)

    async with request_send, request_receive, response_send, response_receive:
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

        async with session:
            await request_send.send(SessionMessage(message=types.JSONRPCMessage(request)))
            response_message = await response_receive.receive()

            root = response_message.message.root
            _ensure(isinstance(root, types.JSONRPCError), "expected a JSON-RPC error response")
            return cast(types.JSONRPCError, root)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "request_id"),
    [
        ("unknown/method", 1),
        ("roots/list", 9),
    ],
)
async def test_client_to_server_unknown_method_returns_method_not_found(method: str, request_id: int) -> None:
    request = types.JSONRPCRequest(jsonrpc="2.0", id=request_id, method=method, params=None)

    error = await _run_client_request(request)

    _assert_error(error, types.METHOD_NOT_FOUND, "Method not found")  # pragma: no cover


@pytest.mark.anyio
async def test_client_to_server_invalid_params_returns_invalid_params() -> None:
    request = types.JSONRPCRequest(jsonrpc="2.0", id=2, method="resources/read", params={})

    error = await _run_client_request(request)

    _assert_error(error, types.INVALID_PARAMS, "Invalid request parameters")  # pragma: no cover


@pytest.mark.anyio
async def test_server_to_client_unknown_method_returns_method_not_found() -> None:
    request = types.JSONRPCRequest(jsonrpc="2.0", id=3, method="server/unknown", params=None)

    error = await _run_server_request(request)

    _assert_error(error, types.METHOD_NOT_FOUND, "Method not found")  # pragma: no cover


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "params", "request_id"),
    [
        ("sampling/createMessage", {}, 4),
        ("roots/list", {"_meta": "invalid"}, 11),
    ],
)
async def test_server_to_client_invalid_params_returns_invalid_params(
    method: str, params: dict[str, object], request_id: int
) -> None:
    request = types.JSONRPCRequest(jsonrpc="2.0", id=request_id, method=method, params=params)

    error = await _run_server_request(request)

    _assert_error(error, types.INVALID_PARAMS, "Invalid request parameters")  # pragma: no cover
