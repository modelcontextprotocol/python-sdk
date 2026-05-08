import anyio
import pytest

from mcp import Client, types
from mcp.client.session import ClientSession
from mcp.server import Server, ServerRequestContext
from mcp.shared._context import RequestContext
from mcp.shared.exceptions import MCPError
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import (
    PARSE_ERROR,
    CancelledNotification,
    CancelledNotificationParams,
    ClientResult,
    EmptyResult,
    ErrorData,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    ServerNotification,
    ServerRequest,
)


@pytest.mark.anyio
async def test_in_flight_requests_cleared_after_completion():
    """Verify that _in_flight is empty after all requests complete."""
    server = Server(name="test server")
    async with Client(server) as client:
        # Send a request and wait for response
        response = await client.send_ping()
        assert isinstance(response, EmptyResult)

        # Verify _in_flight is empty
        assert len(client.session._in_flight) == 0


@pytest.mark.anyio
async def test_request_cancellation():
    """Test that requests can be cancelled while in-flight."""
    ev_tool_called = anyio.Event()
    ev_cancelled = anyio.Event()
    request_id = None

    # Create a server with a slow tool
    async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
        nonlocal request_id, ev_tool_called
        if params.name == "slow_tool":
            request_id = ctx.request_id
            ev_tool_called.set()
            await anyio.sleep(10)  # Long enough to ensure we can cancel
            return types.CallToolResult(content=[])  # pragma: no cover
        raise ValueError(f"Unknown tool: {params.name}")  # pragma: no cover

    async def handle_list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        raise NotImplementedError

    server = Server(
        name="TestSessionServer",
        on_call_tool=handle_call_tool,
        on_list_tools=handle_list_tools,
    )

    async def make_request(client: Client):
        nonlocal ev_cancelled
        try:
            await client.session.send_request(
                types.CallToolRequest(
                    params=types.CallToolRequestParams(name="slow_tool", arguments={}),
                ),
                types.CallToolResult,
            )
            pytest.fail("Request should have been cancelled")  # pragma: no cover
        except MCPError as e:
            # Expected - request was cancelled
            assert "Request cancelled" in str(e)
            ev_cancelled.set()

    async with Client(server) as client:
        async with anyio.create_task_group() as tg:  # pragma: no branch
            tg.start_soon(make_request, client)

            # Wait for the request to be in-flight
            with anyio.fail_after(1):  # Timeout after 1 second
                await ev_tool_called.wait()

            # Send cancellation notification
            assert request_id is not None
            await client.session.send_notification(
                CancelledNotification(params=CancelledNotificationParams(request_id=request_id))
            )

            # Give cancellation time to process
            with anyio.fail_after(1):  # pragma: no branch
                await ev_cancelled.wait()


@pytest.mark.anyio
async def test_response_id_type_mismatch_string_to_int():
    """Test that responses with string IDs are correctly matched to requests sent with
    integer IDs.

    This handles the case where a server returns "id": "0" (string) but the client
    sent "id": 0 (integer). Without ID type normalization, this would cause a timeout.
    """
    ev_response_received = anyio.Event()
    result_holder: list[types.EmptyResult] = []

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async def mock_server():
            """Receive a request and respond with a string ID instead of integer."""
            message = await server_read.receive()
            assert isinstance(message, SessionMessage)
            root = message.message
            assert isinstance(root, JSONRPCRequest)
            # Get the original request ID (which is an integer)
            request_id = root.id
            assert isinstance(request_id, int), f"Expected int, got {type(request_id)}"

            # Respond with the ID as a string (simulating a buggy server)
            response = JSONRPCResponse(
                jsonrpc="2.0",
                id=str(request_id),  # Convert to string to simulate mismatch
                result={},
            )
            await server_write.send(SessionMessage(message=response))

        async def make_request(client_session: ClientSession):
            nonlocal result_holder
            # Send a ping request (uses integer ID internally)
            result = await client_session.send_ping()
            result_holder.append(result)
            ev_response_received.set()

        async with (
            anyio.create_task_group() as tg,
            ClientSession(read_stream=client_read, write_stream=client_write) as client_session,
        ):
            tg.start_soon(mock_server)
            tg.start_soon(make_request, client_session)

            with anyio.fail_after(2):  # pragma: no branch
                await ev_response_received.wait()

    assert len(result_holder) == 1
    assert isinstance(result_holder[0], EmptyResult)


@pytest.mark.anyio
async def test_error_response_id_type_mismatch_string_to_int():
    """Test that error responses with string IDs are correctly matched to requests
    sent with integer IDs.

    This handles the case where a server returns an error with "id": "0" (string)
    but the client sent "id": 0 (integer).
    """
    ev_error_received = anyio.Event()
    error_holder: list[MCPError | Exception] = []

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async def mock_server():
            """Receive a request and respond with an error using a string ID."""
            message = await server_read.receive()
            assert isinstance(message, SessionMessage)
            root = message.message
            assert isinstance(root, JSONRPCRequest)
            request_id = root.id
            assert isinstance(request_id, int)

            # Respond with an error, using the ID as a string
            error_response = JSONRPCError(
                jsonrpc="2.0",
                id=str(request_id),  # Convert to string to simulate mismatch
                error=ErrorData(code=-32600, message="Test error"),
            )
            await server_write.send(SessionMessage(message=error_response))

        async def make_request(client_session: ClientSession):
            nonlocal error_holder
            try:
                await client_session.send_ping()
                pytest.fail("Expected MCPError to be raised")  # pragma: no cover
            except MCPError as e:
                error_holder.append(e)
                ev_error_received.set()

        async with (
            anyio.create_task_group() as tg,
            ClientSession(read_stream=client_read, write_stream=client_write) as client_session,
        ):
            tg.start_soon(mock_server)
            tg.start_soon(make_request, client_session)

            with anyio.fail_after(2):  # pragma: no branch
                await ev_error_received.wait()

    assert len(error_holder) == 1
    assert "Test error" in str(error_holder[0])


@pytest.mark.anyio
async def test_response_id_non_numeric_string_no_match():
    """Test that responses with non-numeric string IDs don't incorrectly match
    integer request IDs.

    If a server returns "id": "abc" (non-numeric string), it should not match
    a request sent with "id": 0 (integer).
    """
    ev_timeout = anyio.Event()

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async def mock_server():
            """Receive a request and respond with a non-numeric string ID."""
            message = await server_read.receive()
            assert isinstance(message, SessionMessage)

            # Respond with a non-numeric string ID (should not match)
            response = JSONRPCResponse(
                jsonrpc="2.0",
                id="not_a_number",  # Non-numeric string
                result={},
            )
            await server_write.send(SessionMessage(message=response))

        async def make_request(client_session: ClientSession):
            try:
                # Use a short timeout since we expect this to fail
                await client_session.send_request(
                    types.PingRequest(),
                    types.EmptyResult,
                    request_read_timeout_seconds=0.5,
                )
                pytest.fail("Expected timeout")  # pragma: no cover
            except MCPError as e:
                assert "Timed out" in str(e)
                ev_timeout.set()

        async with (
            anyio.create_task_group() as tg,
            ClientSession(read_stream=client_read, write_stream=client_write) as client_session,
        ):
            tg.start_soon(mock_server)
            tg.start_soon(make_request, client_session)

            with anyio.fail_after(2):  # pragma: no branch
                await ev_timeout.wait()


@pytest.mark.anyio
async def test_connection_closed():
    """Test that pending requests are cancelled when the connection is closed remotely."""

    ev_closed = anyio.Event()
    ev_response = anyio.Event()

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async def make_request(client_session: ClientSession):
            """Send a request in a separate task"""
            nonlocal ev_response
            try:
                # any request will do
                await client_session.initialize()
                pytest.fail("Request should have errored")  # pragma: no cover
            except MCPError as e:
                # Expected - request errored
                assert "Connection closed" in str(e)
                ev_response.set()

        async def mock_server():
            """Wait for a request, then close the connection"""
            nonlocal ev_closed
            # Wait for a request
            await server_read.receive()
            # Close the connection, as if the server exited
            server_write.close()
            server_read.close()
            ev_closed.set()

        async with (
            anyio.create_task_group() as tg,
            ClientSession(read_stream=client_read, write_stream=client_write) as client_session,
        ):
            tg.start_soon(make_request, client_session)
            tg.start_soon(mock_server)

            with anyio.fail_after(1):
                await ev_closed.wait()
            with anyio.fail_after(1):  # pragma: no branch
                await ev_response.wait()


@pytest.mark.anyio
async def test_null_id_error_surfaced_via_message_handler():
    """Test that a JSONRPCError with id=None is surfaced to the message handler.

    Per JSON-RPC 2.0, error responses use id=null when the request id could not
    be determined (e.g., parse errors). These cannot be correlated to any pending
    request, so they are forwarded to the message handler as MCPError.
    """
    ev_error_received = anyio.Event()
    error_holder: list[MCPError] = []

    async def capture_errors(
        message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
    ) -> None:
        assert isinstance(message, MCPError)
        error_holder.append(message)
        ev_error_received.set()

    sent_error = ErrorData(code=PARSE_ERROR, message="Parse error")

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        _server_read, server_write = server_streams

        async def mock_server():
            """Send a null-id error (simulating a parse error)."""
            error_response = JSONRPCError(jsonrpc="2.0", id=None, error=sent_error)
            await server_write.send(SessionMessage(message=error_response))

        async with (
            anyio.create_task_group() as tg,
            ClientSession(
                read_stream=client_read,
                write_stream=client_write,
                message_handler=capture_errors,
            ) as _client_session,
        ):
            tg.start_soon(mock_server)

            with anyio.fail_after(2):  # pragma: no branch
                await ev_error_received.wait()

    assert len(error_holder) == 1
    assert error_holder[0].error == sent_error


@pytest.mark.anyio
async def test_null_id_error_does_not_affect_pending_request():
    """Test that a null-id error doesn't interfere with an in-flight request.

    When a null-id error arrives while a request is pending, the error should
    go to the message handler and the pending request should still complete
    normally with its own response.
    """
    ev_error_received = anyio.Event()
    ev_response_received = anyio.Event()
    error_holder: list[MCPError] = []
    result_holder: list[EmptyResult] = []

    async def capture_errors(
        message: RequestResponder[ServerRequest, ClientResult] | ServerNotification | Exception,
    ) -> None:
        assert isinstance(message, MCPError)
        error_holder.append(message)
        ev_error_received.set()

    sent_error = ErrorData(code=PARSE_ERROR, message="Parse error")

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async def mock_server():
            """Read a request, inject a null-id error, then respond normally."""
            message = await server_read.receive()
            assert isinstance(message, SessionMessage)
            assert isinstance(message.message, JSONRPCRequest)
            request_id = message.message.id

            # First, send a null-id error (should go to message handler)
            await server_write.send(SessionMessage(message=JSONRPCError(jsonrpc="2.0", id=None, error=sent_error)))

            # Then, respond normally to the pending request
            await server_write.send(SessionMessage(message=JSONRPCResponse(jsonrpc="2.0", id=request_id, result={})))

        async def make_request(client_session: ClientSession):
            result = await client_session.send_ping()
            result_holder.append(result)
            ev_response_received.set()

        async with (
            anyio.create_task_group() as tg,
            ClientSession(
                read_stream=client_read,
                write_stream=client_write,
                message_handler=capture_errors,
            ) as client_session,
        ):
            tg.start_soon(mock_server)
            tg.start_soon(make_request, client_session)

            with anyio.fail_after(2):  # pragma: no branch
                await ev_error_received.wait()
                await ev_response_received.wait()

    # Null-id error reached the message handler
    assert len(error_holder) == 1
    assert error_holder[0].error == sent_error

    # Pending request completed successfully
    assert len(result_holder) == 1
    assert isinstance(result_holder[0], EmptyResult)


@pytest.mark.anyio
async def test_concurrent_server_to_client_requests_run_in_parallel():
    """Regression test for #2489.

    A server tool fans out N concurrent ``ServerSession.create_message`` calls
    via ``anyio.create_task_group``. The client sampling callback records the
    peak number of concurrently-in-flight calls. Before the fix, requests were
    serialized end-to-end by ``BaseSession._receive_loop`` and peak was 1.
    """
    n = 4

    inflight = 0
    peak = 0
    started = anyio.Event()
    release = anyio.Event()

    async def sampling_callback(
        context: RequestContext[ClientSession],
        params: types.CreateMessageRequestParams,
    ) -> types.CreateMessageResult:
        nonlocal inflight, peak
        inflight += 1
        peak = max(peak, inflight)
        if peak == n:
            started.set()
        try:
            with anyio.fail_after(5):
                await release.wait()
        finally:
            inflight -= 1
        msg = params.messages[0].content
        echo = msg.text if isinstance(msg, types.TextContent) else ""
        return types.CreateMessageResult(
            role="assistant",
            content=types.TextContent(type="text", text=f"echo:{echo}"),
            model="test-model",
        )

    async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
        results: list[str] = [""] * n

        async def one(i: int) -> None:
            r = await ctx.session.create_message(
                messages=[
                    types.SamplingMessage(
                        role="user",
                        content=types.TextContent(type="text", text=str(i)),
                    )
                ],
                max_tokens=8,
            )
            results[i] = r.content.text if isinstance(r.content, types.TextContent) else ""

        async with anyio.create_task_group() as tg:  # pragma: no branch
            for i in range(n):
                tg.start_soon(one, i)
        return types.CallToolResult(content=[types.TextContent(type="text", text=",".join(results))])

    async def handle_list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="fanout", input_schema={"type": "object"})])

    server = Server(name="fanout", on_call_tool=handle_call_tool, on_list_tools=handle_list_tools)

    async with Client(server, sampling_callback=sampling_callback) as client:
        async with anyio.create_task_group() as tg:  # pragma: no branch

            async def call() -> None:
                await client.call_tool("fanout", {})

            tg.start_soon(call)
            with anyio.fail_after(5):
                await started.wait()
            release.set()

    assert peak == n, f"server->client requests were serialized: peak in-flight={peak}, expected {n}"


@pytest.mark.anyio
async def test_sampling_callback_exception_returns_error_response():
    """A raising sampling callback must produce a JSON-RPC error response so
    the server-side ``await ctx.session.create_message(...)`` doesn't hang.
    """

    async def sampling_callback(
        context: RequestContext[ClientSession],
        params: types.CreateMessageRequestParams,
    ) -> types.CreateMessageResult:
        raise RuntimeError("boom")

    caught: list[MCPError] = []

    async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
        try:
            await ctx.session.create_message(
                messages=[
                    types.SamplingMessage(
                        role="user",
                        content=types.TextContent(type="text", text="x"),
                    )
                ],
                max_tokens=8,
            )
        except MCPError as e:
            caught.append(e)
        return types.CallToolResult(content=[types.TextContent(type="text", text="ok")])

    async def handle_list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="boom", input_schema={"type": "object"})])

    server = Server(name="raise", on_call_tool=handle_call_tool, on_list_tools=handle_list_tools)

    async with Client(server, sampling_callback=sampling_callback) as client:
        with anyio.fail_after(5):
            await client.call_tool("boom", {})

    assert len(caught) == 1


@pytest.mark.anyio
async def test_double_cancel_does_not_send_second_response():
    """Cancel called twice on the same responder must not emit a second response."""

    class _Dummy:
        _send_response_calls = 0

        async def _send_response(self, *, request_id: types.RequestId, response: object) -> None:
            self._send_response_calls += 1

    dummy = _Dummy()
    responder = RequestResponder[types.ServerRequest, types.ClientResult](
        request_id=1,
        request_meta=None,
        request=types.PingRequest(method="ping"),
        session=dummy,  # type: ignore[arg-type]
        on_complete=lambda _r: None,
    )
    with responder:
        await responder.cancel()
        await responder.cancel()
    assert dummy._send_response_calls == 1


@pytest.mark.anyio
async def test_cancel_before_context_entered_marks_scope_cancelled():
    """Regression: with concurrent dispatch, a CancelledNotification can
    arrive before the handler task has entered ``with responder:``.
    ``cancel()`` must not raise, and the scope entered later must already
    be cancelled.
    """

    class _Dummy:
        async def _send_response(self, *, request_id: types.RequestId, response: object) -> None:
            pass

    responder = RequestResponder[types.ServerRequest, types.ClientResult](
        request_id=7,
        request_meta=None,
        request=types.PingRequest(method="ping"),
        session=_Dummy(),  # type: ignore[arg-type]
        on_complete=lambda _r: None,
    )

    await responder.cancel()
    assert responder.cancelled
    assert responder._cancel_scope.cancel_called


@pytest.mark.anyio
async def test_handler_that_responds_then_raises_emits_no_duplicate_error():
    """If a request handler completes the response and then raises, the
    dispatch path must not emit a second JSON-RPC error for the same id.
    """

    class _RaiseAfterRespond(ClientSession):
        async def _received_request(self, responder: RequestResponder[types.ServerRequest, types.ClientResult]) -> None:
            with responder:
                await responder.respond(types.EmptyResult())
            raise RuntimeError("after respond")

    class _CapturingWrite:
        def __init__(self) -> None:
            self.sent: list[SessionMessage] = []

        async def send(self, msg: SessionMessage) -> None:
            self.sent.append(msg)

    async with create_client_server_memory_streams() as (client_streams, _server_streams):
        client_read, client_write = client_streams
        session = _RaiseAfterRespond(client_read, client_write)

        capture = _CapturingWrite()
        session._write_stream = capture  # type: ignore[assignment]

        responder = RequestResponder[types.ServerRequest, types.ClientResult](
            request_id=99,
            request_meta=None,
            request=types.PingRequest(method="ping"),
            session=session,
            on_complete=lambda r: session._in_flight.pop(r.request_id, None),
        )
        session._in_flight[99] = responder

        await session._dispatch_request(responder)

    assert len(capture.sent) == 1, capture.sent
    assert isinstance(capture.sent[0].message, JSONRPCResponse)
    assert capture.sent[0].message.id == 99
