"""Tests for automatic session recovery on 404/SESSION_EXPIRED errors.

Per MCP spec, when a client receives HTTP 404 in response to a request containing
an MCP-Session-Id, it MUST start a new session by sending a new InitializeRequest
without a session ID attached.
"""

from typing import Any

import anyio
import pytest

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.shared.exceptions import McpError
from mcp.shared.message import SessionMessage
from mcp.types import (
    CONNECTION_CLOSED,
    LATEST_PROTOCOL_VERSION,
    SESSION_EXPIRED,
    CallToolResult,
    ClientRequest,
    ErrorData,
    Implementation,
    InitializeRequest,
    InitializeResult,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCRequest,
    JSONRPCResponse,
    ServerCapabilities,
    ServerResult,
    TextContent,
    Tool,
)


@pytest.mark.anyio
async def test_session_recovery_on_expired_error():
    """Test that client re-initializes session when receiving SESSION_EXPIRED error."""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)

    init_count = 0
    tool_call_count = 0

    async def mock_server():
        nonlocal init_count, tool_call_count

        # First initialization
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        request = ClientRequest.model_validate(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request.root, InitializeRequest)
        init_count += 1

        # Send init response
        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=ServerResult(
                            InitializeResult(
                                protocolVersion=LATEST_PROTOCOL_VERSION,
                                capabilities=ServerCapabilities(),
                                serverInfo=Implementation(name="mock-server", version="0.1.0"),
                            )
                        ).model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )

        # Receive initialized notification
        await client_to_server_receive.receive()

        # Receive tool call request
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        assert jsonrpc_request.root.method == "tools/call"
        tool_call_count += 1

        # Send SESSION_EXPIRED error (simulating 404 from transport)
        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCError(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        error=ErrorData(
                            code=SESSION_EXPIRED,
                            message="Session expired, re-initialization required",
                        ),
                    )
                )
            )
        )

        # Should receive second initialization request (automatic recovery)
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        request = ClientRequest.model_validate(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request.root, InitializeRequest)
        init_count += 1

        # Send second init response
        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=ServerResult(
                            InitializeResult(
                                protocolVersion=LATEST_PROTOCOL_VERSION,
                                capabilities=ServerCapabilities(),
                                serverInfo=Implementation(name="mock-server", version="0.1.0"),
                            )
                        ).model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )

        # Receive initialized notification
        await client_to_server_receive.receive()

        # Receive retried tool call
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        assert jsonrpc_request.root.method == "tools/call"
        tool_call_count += 1

        # Send successful response this time
        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=ServerResult(
                            CallToolResult(
                                content=[TextContent(type="text", text="Success!")],
                                isError=False,
                            )
                        ).model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )

        # call_tool validates result by calling list_tools
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        assert jsonrpc_request.root.method == "tools/list"

        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=types.ListToolsResult(tools=[Tool(name="test_tool", inputSchema={})]).model_dump(
                            by_alias=True, mode="json", exclude_none=True
                        ),
                    )
                )
            )
        )

        server_to_client_send.close()

    async with (
        ClientSession(
            server_to_client_receive,
            client_to_server_send,
        ) as session,
        anyio.create_task_group() as tg,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        tg.start_soon(mock_server)

        await session.initialize()

        # This should trigger SESSION_EXPIRED, then auto-reinit, then retry
        result = await session.call_tool("test_tool", {"foo": "bar"})

        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Success!"

    # Verify: 2 initializations (original + recovery), 2 tool calls (failed + retried)
    assert init_count == 2
    assert tool_call_count == 2


@pytest.mark.anyio
async def test_no_infinite_retry_loop_on_repeated_session_expired():
    """Test that client doesn't loop infinitely when session keeps expiring."""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)

    init_count = 0

    async def mock_server():
        nonlocal init_count

        # First initialization
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        init_count += 1

        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=ServerResult(
                            InitializeResult(
                                protocolVersion=LATEST_PROTOCOL_VERSION,
                                capabilities=ServerCapabilities(),
                                serverInfo=Implementation(name="mock-server", version="0.1.0"),
                            )
                        ).model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )

        # Receive initialized notification
        await client_to_server_receive.receive()

        # Receive tool call
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)

        # Send SESSION_EXPIRED
        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCError(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        error=ErrorData(
                            code=SESSION_EXPIRED,
                            message="Session expired",
                        ),
                    )
                )
            )
        )

        # Second initialization (automatic recovery)
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        init_count += 1

        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=ServerResult(
                            InitializeResult(
                                protocolVersion=LATEST_PROTOCOL_VERSION,
                                capabilities=ServerCapabilities(),
                                serverInfo=Implementation(name="mock-server", version="0.1.0"),
                            )
                        ).model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )

        # Receive initialized notification
        await client_to_server_receive.receive()

        # Receive retried tool call
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)

        # Send SESSION_EXPIRED AGAIN - should NOT trigger another reinit
        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCError(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        error=ErrorData(
                            code=SESSION_EXPIRED,
                            message="Session expired again",
                        ),
                    )
                )
            )
        )

        server_to_client_send.close()

    async with (
        ClientSession(
            server_to_client_receive,
            client_to_server_send,
        ) as session,
        anyio.create_task_group() as tg,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        tg.start_soon(mock_server)

        await session.initialize()

        # Should raise McpError after retry fails (no infinite loop)
        with pytest.raises(McpError) as exc_info:
            await session.call_tool("test_tool", {})

        assert exc_info.value.error.code == SESSION_EXPIRED

    # Only 2 initializations: original + one recovery attempt
    assert init_count == 2


@pytest.mark.anyio
async def test_non_session_expired_error_not_retried():
    """Test that other MCP errors don't trigger session recovery."""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)

    init_count = 0

    async def mock_server():
        nonlocal init_count

        # Initial initialization
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        init_count += 1

        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=ServerResult(
                            InitializeResult(
                                protocolVersion=LATEST_PROTOCOL_VERSION,
                                capabilities=ServerCapabilities(),
                                serverInfo=Implementation(name="mock-server", version="0.1.0"),
                            )
                        ).model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )

        # Receive initialized notification
        await client_to_server_receive.receive()

        # Receive tool call
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)

        # Send a different error (CONNECTION_CLOSED)
        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCError(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        error=ErrorData(
                            code=CONNECTION_CLOSED,
                            message="Connection closed",
                        ),
                    )
                )
            )
        )

        server_to_client_send.close()

    async with (
        ClientSession(
            server_to_client_receive,
            client_to_server_send,
        ) as session,
        anyio.create_task_group() as tg,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        tg.start_soon(mock_server)

        await session.initialize()

        # Should raise McpError directly without recovery attempt
        with pytest.raises(McpError) as exc_info:
            await session.call_tool("test_tool", {})

        assert exc_info.value.error.code == CONNECTION_CLOSED

    # Only 1 initialization - no recovery triggered
    assert init_count == 1


@pytest.mark.anyio
async def test_session_recovery_preserves_request_data():
    """Test that the original request data is preserved through recovery."""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)

    tool_params_received: list[dict[str, Any]] = []

    async def mock_server():
        # First initialization
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)

        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=ServerResult(
                            InitializeResult(
                                protocolVersion=LATEST_PROTOCOL_VERSION,
                                capabilities=ServerCapabilities(),
                                serverInfo=Implementation(name="mock-server", version="0.1.0"),
                            )
                        ).model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )

        # Receive initialized notification
        await client_to_server_receive.receive()

        # Receive first tool call
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        assert jsonrpc_request.root.params is not None
        tool_params_received.append(jsonrpc_request.root.params)

        # Send SESSION_EXPIRED
        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCError(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        error=ErrorData(
                            code=SESSION_EXPIRED,
                            message="Session expired",
                        ),
                    )
                )
            )
        )

        # Second initialization (recovery)
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)

        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=ServerResult(
                            InitializeResult(
                                protocolVersion=LATEST_PROTOCOL_VERSION,
                                capabilities=ServerCapabilities(),
                                serverInfo=Implementation(name="mock-server", version="0.1.0"),
                            )
                        ).model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )

        # Receive initialized notification
        await client_to_server_receive.receive()

        # Receive retried tool call - should have same params
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        assert jsonrpc_request.root.params is not None
        tool_params_received.append(jsonrpc_request.root.params)

        # Send success
        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=ServerResult(
                            CallToolResult(
                                content=[TextContent(type="text", text="Done")],
                                isError=False,
                            )
                        ).model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )

        # call_tool validates result by calling list_tools
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        assert jsonrpc_request.root.method == "tools/list"

        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=types.ListToolsResult(tools=[Tool(name="important_tool", inputSchema={})]).model_dump(
                            by_alias=True, mode="json", exclude_none=True
                        ),
                    )
                )
            )
        )

        server_to_client_send.close()

    async with (
        ClientSession(
            server_to_client_receive,
            client_to_server_send,
        ) as session,
        anyio.create_task_group() as tg,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        tg.start_soon(mock_server)

        await session.initialize()

        # Call with specific arguments
        await session.call_tool("important_tool", {"key": "sensitive_value", "count": 42})

    # Both tool calls should have identical parameters
    assert len(tool_params_received) == 2
    assert tool_params_received[0] == tool_params_received[1]
    assert tool_params_received[0]["name"] == "important_tool"
    assert tool_params_received[0]["arguments"] == {"key": "sensitive_value", "count": 42}


@pytest.mark.anyio
async def test_streamable_http_transport_404_sends_session_expired():
    """Test that HTTP transport converts 404 response to SESSION_EXPIRED error.

    This tests the transport layer directly to ensure the 404 -> SESSION_EXPIRED
    conversion happens correctly in streamable_http.py.
    """
    import json

    import httpx

    from mcp.client.streamable_http import StreamableHTTPTransport

    # Track requests to simulate different responses
    request_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1

        if request_count == 1:
            # First request (initialize) - return success with SSE
            init_response = {
                "jsonrpc": "2.0",
                "id": 0,
                "result": {
                    "protocolVersion": LATEST_PROTOCOL_VERSION,
                    "capabilities": {},
                    "serverInfo": {"name": "mock", "version": "0.1.0"},
                },
            }
            sse_data = f"event: message\ndata: {json.dumps(init_response)}\n\n"
            return httpx.Response(
                200,
                content=sse_data.encode(),
                headers={
                    "Content-Type": "text/event-stream",
                    "mcp-session-id": "test-session-123",
                },
            )
        else:
            # Second request - return 404 (session not found)
            return httpx.Response(404, content=b"Session not found")

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)

    # Create the transport
    streamable_transport = StreamableHTTPTransport("http://example.com/mcp")

    # Set up streams - read_send needs to accept SessionMessage | Exception
    read_send, read_receive = anyio.create_memory_object_stream[SessionMessage | Exception](10)
    write_send, write_receive = anyio.create_memory_object_stream[SessionMessage](10)

    # Send an initialization request
    init_request = JSONRPCMessage(
        JSONRPCRequest(
            jsonrpc="2.0",
            id=0,
            method="initialize",
            params={
                "protocolVersion": LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.1.0"},
            },
        )
    )

    try:
        async with anyio.create_task_group() as tg:
            get_stream_started = False

            def start_get_stream() -> None:
                nonlocal get_stream_started
                get_stream_started = True

            async def run_post_writer():
                await streamable_transport.post_writer(
                    http_client,
                    write_receive,
                    read_send,
                    write_send,
                    start_get_stream,
                    tg,
                )

            tg.start_soon(run_post_writer)

            # Send init request
            await write_send.send(SessionMessage(init_request))

            # Get init response
            received = await read_receive.receive()
            assert isinstance(received, SessionMessage)
            response = received
            assert isinstance(response.message.root, JSONRPCResponse)

            # Now send a tool call request (will get 404)
            tool_request = JSONRPCMessage(
                JSONRPCRequest(
                    jsonrpc="2.0",
                    id=1,
                    method="tools/call",
                    params={"name": "test_tool", "arguments": {}},
                )
            )
            await write_send.send(SessionMessage(tool_request))

            # Should receive SESSION_EXPIRED error
            received = await read_receive.receive()
            assert isinstance(received, SessionMessage)
            error_response = received
            assert isinstance(error_response.message.root, JSONRPCError)
            assert error_response.message.root.error.code == SESSION_EXPIRED

            # Verify session_id was cleared
            assert streamable_transport.session_id is None

            tg.cancel_scope.cancel()
    finally:
        # Proper cleanup of all streams
        await write_send.aclose()
        await write_receive.aclose()
        await read_send.aclose()
        await read_receive.aclose()
        await http_client.aclose()


@pytest.mark.anyio
async def test_streamable_http_transport_404_on_init_sends_terminated():
    """Test that 404 on initialization request sends session terminated error.

    When the server returns 404 for an initialization request, it means the
    session truly doesn't exist (not expired), so we send a different error.
    """
    import httpx

    from mcp.client.streamable_http import StreamableHTTPTransport

    def mock_handler(request: httpx.Request) -> httpx.Response:
        # Return 404 for initialization request
        return httpx.Response(404, content=b"Session not found")

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)

    streamable_transport = StreamableHTTPTransport("http://example.com/mcp")

    # Set up streams - read_send needs to accept SessionMessage | Exception
    read_send, read_receive = anyio.create_memory_object_stream[SessionMessage | Exception](10)
    write_send, write_receive = anyio.create_memory_object_stream[SessionMessage](10)

    init_request = JSONRPCMessage(
        JSONRPCRequest(
            jsonrpc="2.0",
            id=0,
            method="initialize",
            params={
                "protocolVersion": LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.1.0"},
            },
        )
    )

    try:
        async with anyio.create_task_group() as tg:

            def start_get_stream() -> None:
                pass  # No-op for this test

            async def run_post_writer():
                await streamable_transport.post_writer(
                    http_client,
                    write_receive,
                    read_send,
                    write_send,
                    start_get_stream,
                    tg,
                )

            tg.start_soon(run_post_writer)

            # Send init request
            await write_send.send(SessionMessage(init_request))

            # Should receive session terminated error (not expired)
            received = await read_receive.receive()
            assert isinstance(received, SessionMessage)
            error_response = received
            assert isinstance(error_response.message.root, JSONRPCError)
            # For initialization 404, we send session terminated, not expired
            assert error_response.message.root.error.code == 32600  # Session terminated

            tg.cancel_scope.cancel()
    finally:
        # Proper cleanup of all streams
        await write_send.aclose()
        await write_receive.aclose()
        await read_send.aclose()
        await read_receive.aclose()
        await http_client.aclose()
