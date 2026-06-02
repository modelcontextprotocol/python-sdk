"""Wire-level invariants observed at the client's transport boundary.

These behaviours are invisible to API callers -- they are properties of the raw JSON-RPC frames.
The tests wrap the in-memory transport in a RecordingTransport, which tees every message crossing
the transport seam into a list without touching the session, so the assertions hold for whatever
the session implementation sends rather than for what its API returns.

The later tests drive the wire by hand instead: one closes the server-to-client stream while a
request is in flight to pin the connection-closed teardown, and the last two send deliberately
malformed JSON-RPC requests that the typed client API cannot produce.
"""

import anyio
import pytest
from inline_snapshot import snapshot

from mcp import MCPError, types
from mcp.client import ClientRequestContext, ClientSession
from mcp.client._memory import InMemoryTransport
from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from mcp.types import (
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
from tests.interaction._helpers import RecordingTransport, _RecordingReadStream
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


def _echo_server() -> Server:
    """A server with one echo tool, used by every test in this module."""

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
    """Every request the client sends carries a distinct, non-null id.

    The id sequence is pinned: sequential integers from zero, in send order.
    """
    recording = RecordingTransport(InMemoryTransport(_echo_server()))

    async with Client(recording) as client:
        await client.list_tools()
        await client.call_tool("echo", {})
        await client.call_tool("echo", {})
        await client.send_ping()

    sent = [message.message for message in recording.sent]
    request_ids = [message.id for message in sent if isinstance(message, JSONRPCRequest)]
    assert all(request_id is not None for request_id in request_ids)
    assert len(request_ids) == len(set(request_ids))
    # initialize, tools/list, tools/call, tools/call, ping -- the client does not issue a
    # schema-cache refresh here because the explicit tools/list already populated the cache.
    assert request_ids == snapshot([0, 1, 2, 3, 4])


@requirement("protocol:notifications:no-response")
async def test_notifications_are_never_answered() -> None:
    """A notification produces no response: everything the server sends back answers a request.

    The client sends two notifications (initialized and roots/list_changed) and several requests;
    the messages received from the server must be exactly one response per request, each carrying
    the id of the request it answers, and nothing else.
    """

    async def list_roots(context: ClientRequestContext) -> ListRootsResult:
        """Registered so the client declares the roots capability; the server never asks for roots."""
        raise NotImplementedError

    recording = RecordingTransport(InMemoryTransport(_echo_server()))

    async with Client(recording, list_roots_callback=list_roots) as client:
        await client.send_roots_list_changed()
        await client.send_ping()

    sent = [message.message for message in recording.sent]
    sent_request_ids = [message.id for message in sent if isinstance(message, JSONRPCRequest)]
    sent_notifications = [message for message in sent if isinstance(message, JSONRPCNotification)]
    received = [message.message for message in recording.received if isinstance(message, SessionMessage)]
    received_responses = [message for message in received if isinstance(message, JSONRPCResponse)]

    assert len(sent_notifications) == 2  # notifications/initialized and notifications/roots/list_changed
    assert len(received_responses) == len(received)  # nothing the server sent was anything but a response
    assert [message.id for message in received_responses] == sent_request_ids


async def test_recording_read_stream_ends_iteration_when_the_sender_closes() -> None:
    """The recording wrapper preserves the end-of-stream behaviour of the stream it wraps.

    This exercises the helper itself rather than an interaction-model behaviour: a transport whose
    far end closes must end the client's receive loop cleanly, and the wrapper must not swallow or
    mistranslate that.
    """
    send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    log: list[SessionMessage | Exception] = []
    async with send_stream, _RecordingReadStream(receive_stream, log) as wrapped:
        await send_stream.aclose()
        items = [item async for item in wrapped]
    assert items == []
    assert log == []


@requirement("lifecycle:initialized-notification")
async def test_exactly_one_initialized_notification_is_sent_after_the_handshake() -> None:
    """The client sends initialized exactly once, between the initialize response and its first request.

    The full method sequence the client puts on the wire is pinned in send order.
    """
    recording = RecordingTransport(InMemoryTransport(_echo_server()))

    async with Client(recording) as client:
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
    """When the server-to-client stream closes, every in-flight client request fails with CONNECTION_CLOSED.

    Driven over a bare ClientSession against a real Server so the test holds the transport stream
    pair directly: once the request is in flight (the server handler signals it has started) the
    test closes the server's write stream, which ends the client's receive loop and triggers the
    teardown that fails the pending request.
    """
    handler_started = anyio.Event()

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "block"
        handler_started.set()
        await anyio.Event().wait()  # blocks until cancelled; nothing ever sets this event
        raise NotImplementedError  # unreachable: the wait above never completes normally

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
    """A request whose params fail validation is answered with -32602 Invalid params.

    The typed client API cannot construct a request with the wrong parameter types, so the test
    plays the client's side of the wire by hand against a real Server: it completes the
    initialization handshake at the JSON-RPC layer and then sends a tools/call whose `name` is an
    integer. Reserve this pattern for behaviour the typed API cannot produce.
    """
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
    """logging/setLevel with a value outside the spec's level enum is answered with -32602 Invalid params.

    The typed client API cannot construct a setLevel request with an unrecognized level (pyright and
    the client-side model both reject it), so the test plays the client's side of the wire by hand
    against a real Server. Reserve this pattern for behaviour the typed API cannot produce.
    """

    async def set_logging_level(ctx: ServerRequestContext, params: types.SetLevelRequestParams) -> EmptyResult:
        """Registered so the logging capability is advertised; never called -- params validation fails first."""
        raise NotImplementedError

    server = Server("logger", on_set_logging_level=set_logging_level)
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
