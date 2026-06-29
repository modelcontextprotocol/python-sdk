"""Wire-level invariants observed at the client's transport boundary.

RecordingTransport tees every frame crossing the transport seam, so assertions hold for what the
session sends rather than what its API returns. The later tests drive the wire by hand instead,
producing conditions the typed client API cannot: a mid-request close and malformed requests.
"""

import anyio
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    CONNECTION_CLOSED,
    INVALID_PARAMS,
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    EmptyResult,
    ErrorData,
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ListRootsResult,
    TextContent,
)

from mcp import MCPError
from mcp.client import ClientRequestContext, ClientSession
from mcp.client._memory import InMemoryTransport
from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from tests.interaction._helpers import RecordingTransport, _RecordingReadStream
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


def _echo_server() -> Server:
    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="echo", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "echo"
        return CallToolResult(content=[TextContent(text="ok")])

    return Server("wire", on_list_tools=list_tools, on_call_tool=call_tool)


@requirement("protocol:request-id:unique")
async def test_request_ids_are_unique_and_never_null() -> None:
    recording = RecordingTransport(InMemoryTransport(_echo_server()))

    async with Client(recording, mode="legacy") as client:
        await client.list_tools()
        await client.call_tool("echo", {})
        await client.call_tool("echo", {})
        await client.send_ping()  # pyright: ignore[reportDeprecated]

    sent = [message.message for message in recording.sent]
    request_ids = [message.id for message in sent if isinstance(message, JSONRPCRequest)]
    assert all(request_id is not None for request_id in request_ids)
    assert len(request_ids) == len(set(request_ids))
    # initialize, tools/list, tools/call x2, ping -- no schema-cache refresh; the explicit tools/list filled the cache
    assert request_ids == snapshot([1, 2, 3, 4, 5])


@requirement("protocol:notifications:no-response")
async def test_notifications_are_never_answered() -> None:
    async def list_roots(context: ClientRequestContext) -> ListRootsResult:
        """Registered so the client declares the roots capability; the server never asks for roots."""
        raise NotImplementedError

    recording = RecordingTransport(InMemoryTransport(_echo_server()))

    async with Client(recording, mode="legacy", list_roots_callback=list_roots) as client:
        await client.send_roots_list_changed()  # pyright: ignore[reportDeprecated]
        await client.send_ping()  # pyright: ignore[reportDeprecated]

    sent = [message.message for message in recording.sent]
    sent_request_ids = [message.id for message in sent if isinstance(message, JSONRPCRequest)]
    sent_notifications = [message for message in sent if isinstance(message, JSONRPCNotification)]
    received = [message.message for message in recording.received if isinstance(message, SessionMessage)]
    received_responses = [message for message in received if isinstance(message, JSONRPCResponse)]

    assert len(sent_notifications) == 2  # notifications/initialized and notifications/roots/list_changed
    assert len(received_responses) == len(received)  # nothing the server sent was anything but a response
    assert [message.id for message in received_responses] == sent_request_ids


async def test_recording_read_stream_ends_iteration_when_the_sender_closes() -> None:
    """Exercises the helper itself: the wrapper must preserve, not swallow, the wrapped stream's end-of-stream."""
    send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    log: list[SessionMessage | Exception] = []
    async with send_stream, _RecordingReadStream(receive_stream, log) as wrapped:
        await send_stream.aclose()
        items = [item async for item in wrapped]
    assert items == []
    assert log == []


@requirement("lifecycle:initialized-notification")
async def test_exactly_one_initialized_notification_is_sent_after_the_handshake() -> None:
    recording = RecordingTransport(InMemoryTransport(_echo_server()))

    async with Client(recording, mode="legacy") as client:
        await client.list_tools()

    sent_methods = [
        message.message.method
        for message in recording.sent
        if isinstance(message.message, JSONRPCRequest | JSONRPCNotification)
    ]
    assert sent_methods.count("notifications/initialized") == 1
    assert sent_methods == snapshot(["initialize", "notifications/initialized", "tools/list"])


@requirement("protocol:error:connection-closed")
async def test_closing_the_transport_fails_in_flight_requests_with_connection_closed() -> None:
    """Driven over a bare ClientSession so the test holds the raw streams and can close the server's write side."""
    handler_started = anyio.Event()

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "block"
        handler_started.set()
        await anyio.Event().wait()  # blocks until cancelled
        raise NotImplementedError  # unreachable

    server = Server("blocker", on_call_tool=call_tool)

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        errors: list[ErrorData] = []

        async with anyio.create_task_group() as server_task_group:
            server_task_group.start_soon(server.run, server_read, server_write, server.create_initialization_options())

            async with ClientSession(client_read, client_write) as session:
                with anyio.fail_after(5):
                    await session.initialize()

                    async def call_and_capture_error() -> None:
                        with pytest.raises(MCPError) as exc_info:
                            await session.send_request(
                                CallToolRequest(params=CallToolRequestParams(name="block")), CallToolResult
                            )
                        errors.append(exc_info.value.error)

                    async with anyio.create_task_group() as task_group:  # pragma: no branch
                        task_group.start_soon(call_and_capture_error)
                        await handler_started.wait()
                        await server_write.aclose()

            server_task_group.cancel_scope.cancel()

    assert errors == snapshot([ErrorData(code=CONNECTION_CLOSED, message="Connection closed")])


@requirement("protocol:error:invalid-params")
async def test_malformed_request_params_are_answered_with_invalid_params() -> None:
    """Plays the client's wire by hand: the typed API cannot produce a tools/call with an integer `name`."""
    server = Server("strict")
    errors: list[ErrorData] = []

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as server_task_group:
            server_task_group.start_soon(server.run, server_read, server_write, server.create_initialization_options())

            with anyio.fail_after(5):
                await client_write.send(
                    SessionMessage(
                        JSONRPCRequest(
                            jsonrpc="2.0",
                            id=0,
                            method="initialize",
                            params={
                                "protocolVersion": "2025-11-25",
                                "capabilities": {},
                                "clientInfo": {"name": "raw", "version": "0.0.1"},
                            },
                        )
                    )
                )
                init_response = await client_read.receive()
                assert isinstance(init_response, SessionMessage)
                assert isinstance(init_response.message, JSONRPCResponse)
                await client_write.send(
                    SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized"))
                )

                await client_write.send(
                    SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=1, method="tools/call", params={"name": 42}))
                )
                error_response = await client_read.receive()
                assert isinstance(error_response, SessionMessage)
                assert isinstance(error_response.message, JSONRPCError)
                errors.append(error_response.message.error)

            server_task_group.cancel_scope.cancel()

    assert errors == snapshot([ErrorData(code=INVALID_PARAMS, message="Invalid request parameters", data="")])


@requirement("logging:set-level:invalid-level")
async def test_set_level_with_an_unrecognized_value_is_answered_with_invalid_params() -> None:
    """Plays the client's wire by hand: the typed API rejects an unrecognized level before it reaches the wire."""

    async def set_logging_level(ctx: ServerRequestContext, params: types.SetLevelRequestParams) -> EmptyResult:
        """Registered so the logging capability is advertised; never called -- params validation fails first."""
        raise NotImplementedError

    server = Server("logger", on_set_logging_level=set_logging_level)  # pyright: ignore[reportDeprecated]
    errors: list[ErrorData] = []

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as server_task_group:
            server_task_group.start_soon(server.run, server_read, server_write, server.create_initialization_options())

            with anyio.fail_after(5):
                await client_write.send(
                    SessionMessage(
                        JSONRPCRequest(
                            jsonrpc="2.0",
                            id=0,
                            method="initialize",
                            params={
                                "protocolVersion": "2025-11-25",
                                "capabilities": {},
                                "clientInfo": {"name": "raw", "version": "0.0.1"},
                            },
                        )
                    )
                )
                init_response = await client_read.receive()
                assert isinstance(init_response, SessionMessage)
                assert isinstance(init_response.message, JSONRPCResponse)
                await client_write.send(
                    SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized"))
                )

                await client_write.send(
                    SessionMessage(
                        JSONRPCRequest(jsonrpc="2.0", id=1, method="logging/setLevel", params={"level": "loud"})
                    )
                )
                error_response = await client_read.receive()
                assert isinstance(error_response, SessionMessage)
                assert isinstance(error_response.message, JSONRPCError)
                errors.append(error_response.message.error)

            server_task_group.cancel_scope.cancel()

    assert len(errors) == 1
    assert errors[0].code == INVALID_PARAMS
