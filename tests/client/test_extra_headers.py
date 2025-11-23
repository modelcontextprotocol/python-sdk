"""Tests for per-request headers functionality in call_tool."""

import anyio
import pytest

from mcp.client.session import ClientSession
from mcp.shared.message import ClientMessageMetadata, SessionMessage
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    CallToolResult,
    ClientRequest,
    Implementation,
    InitializeRequest,
    InitializeResult,
    JSONRPCMessage,
    JSONRPCRequest,
    JSONRPCResponse,
    ListToolsResult,
    ServerCapabilities,
    ServerResult,
    TextContent,
    Tool,
)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "extra_headers",
    [
        None,
        {},
        {"X-Auth-Token": "user-123-token", "X-Trace-Id": "trace-456"},
    ],
)
async def test_call_tool_with_extra_headers(extra_headers: dict[str, str] | None):
    """Test that call_tool properly handles extra_headers parameter."""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    mocked_tool = Tool(name="test_tool", inputSchema={})

    async def mock_server():
        # Receive initialization request from client
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        request = ClientRequest.model_validate(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request.root, InitializeRequest)

        result = ServerResult(
            InitializeResult(
                protocolVersion=LATEST_PROTOCOL_VERSION,
                capabilities=ServerCapabilities(),
                serverInfo=Implementation(name="mock-server", version="0.1.0"),
            )
        )

        # Answer initialization request
        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )

        # Receive initialized notification
        await client_to_server_receive.receive()

        # Wait for the client to send a 'tools/call' request
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)

        assert jsonrpc_request.root.method == "tools/call"

        # Verify that extra_headers are passed through metadata
        if extra_headers:
            # Check if the session message has metadata with extra headers
            assert session_message.metadata is not None
            assert isinstance(session_message.metadata, ClientMessageMetadata)
            assert session_message.metadata.extra_headers == extra_headers

        result = ServerResult(
            CallToolResult(content=[TextContent(type="text", text="Called successfully")], isError=False)
        )

        # Send the tools/call result
        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )

        # Wait for the tools/list request from the client
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)

        assert jsonrpc_request.root.method == "tools/list"

        result = ListToolsResult(tools=[mocked_tool])

        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
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

        # Call tool with extra_headers
        result = await session.call_tool(name=mocked_tool.name, arguments={"foo": "bar"}, extra_headers=extra_headers)

        assert isinstance(result, CallToolResult)
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Called successfully"


@pytest.mark.anyio
async def test_call_tool_combined_parameters():
    """Test call_tool with extra_headers combined with other parameters."""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    mocked_tool = Tool(name="test_tool", inputSchema={})
    extra_headers = {"X-Custom": "test-value"}
    meta = {"test_meta": "meta_value"}

    async def mock_server():
        # Receive initialization request from client
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        request = ClientRequest.model_validate(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request.root, InitializeRequest)

        result = ServerResult(
            InitializeResult(
                protocolVersion=LATEST_PROTOCOL_VERSION,
                capabilities=ServerCapabilities(),
                serverInfo=Implementation(name="mock-server", version="0.1.0"),
            )
        )

        # Answer initialization request
        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )

        # Receive initialized notification
        await client_to_server_receive.receive()

        # Wait for the client to send a 'tools/call' request
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)

        assert jsonrpc_request.root.method == "tools/call"

        # Verify that meta is in the JSON-RPC params
        assert jsonrpc_request.root.params
        assert "_meta" in jsonrpc_request.root.params
        assert jsonrpc_request.root.params["_meta"] == meta

        # Verify that extra_headers are in the session message metadata
        assert session_message.metadata is not None
        assert isinstance(session_message.metadata, ClientMessageMetadata)
        assert session_message.metadata.extra_headers == extra_headers

        result = ServerResult(
            CallToolResult(content=[TextContent(type="text", text="Called successfully")], isError=False)
        )

        # Send the tools/call result
        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )

        # Wait for the tools/list request from the client
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)

        assert jsonrpc_request.root.method == "tools/list"

        result = ListToolsResult(tools=[mocked_tool])

        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
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

        # Call tool with both meta and extra_headers
        result = await session.call_tool(
            name=mocked_tool.name, arguments={"arg1": "value1"}, meta=meta, extra_headers=extra_headers
        )

        assert isinstance(result, CallToolResult)
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "Called successfully"


def test_client_message_metadata_extra_headers():
    """Test that ClientMessageMetadata properly handles extra_headers."""
    # Test with extra_headers
    headers = {"X-Test": "value", "Authorization": "Bearer token"}
    metadata = ClientMessageMetadata(extra_headers=headers)
    assert metadata.extra_headers == headers

    # Test without extra_headers
    metadata = ClientMessageMetadata()
    assert metadata.extra_headers is None

    # Test with all fields
    metadata = ClientMessageMetadata(resumption_token="token-123", extra_headers=headers)
    assert metadata.resumption_token == "token-123"
    assert metadata.extra_headers == headers


@pytest.mark.anyio
@pytest.mark.parametrize(
    "extra_headers",
    [
        None,
        {},
        {"X-Log-Level": "debug", "X-Trace-Id": "trace-789"},
    ],
)
async def test_set_logging_level_with_extra_headers(extra_headers: dict[str, str] | None):
    """Test that set_logging_level properly handles extra_headers parameter."""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    async def mock_server():
        # Receive initialization request from client
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)

        # Answer initialization request
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

        # Wait for the client to send a 'logging/setLevel' request
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        assert jsonrpc_request.root.method == "logging/setLevel"

        # Verify that extra_headers are passed through metadata
        if extra_headers:
            assert session_message.metadata is not None
            assert isinstance(session_message.metadata, ClientMessageMetadata)
            assert session_message.metadata.extra_headers == extra_headers

        # Send response
        from mcp.types import EmptyResult

        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=ServerResult(EmptyResult()).model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )
        server_to_client_send.close()

    async with (
        ClientSession(server_to_client_receive, client_to_server_send) as session,
        anyio.create_task_group() as tg,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        tg.start_soon(mock_server)
        await session.initialize()

        # Call set_logging_level with extra_headers
        result = await session.set_logging_level("debug", extra_headers=extra_headers)

        from mcp.types import EmptyResult

        assert isinstance(result, EmptyResult)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "extra_headers",
    [
        None,
        {},
        {"X-Resource-Filter": "public", "X-Trace-Id": "trace-123"},
    ],
)
async def test_list_resources_with_extra_headers(extra_headers: dict[str, str] | None):
    """Test that list_resources properly handles extra_headers parameter."""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    async def mock_server():
        # Handle initialization
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

        # Wait for the client to send a 'resources/list' request
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        assert jsonrpc_request.root.method == "resources/list"

        # Verify extra_headers metadata
        if extra_headers:
            assert session_message.metadata is not None
            assert isinstance(session_message.metadata, ClientMessageMetadata)
            assert session_message.metadata.extra_headers == extra_headers

        # Send response
        from mcp.types import ListResourcesResult

        result = ServerResult(ListResourcesResult(resources=[]))
        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )
        server_to_client_send.close()

    async with (
        ClientSession(server_to_client_receive, client_to_server_send) as session,
        anyio.create_task_group() as tg,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        tg.start_soon(mock_server)
        await session.initialize()

        # Call list_resources with extra_headers
        result = await session.list_resources(extra_headers=extra_headers)

        from mcp.types import ListResourcesResult

        assert isinstance(result, ListResourcesResult)


@pytest.mark.anyio
async def test_all_methods_without_extra_headers():
    """Test that all extended methods work correctly without extra_headers (no regression)."""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)

    request_count = 0

    async def mock_server():
        nonlocal request_count

        # Handle initialization
        session_message = await client_to_server_receive.receive()
        request_count += 1
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

        # Handle each method call
        while True:
            try:
                session_message = await client_to_server_receive.receive()
                request_count += 1
                jsonrpc_request = session_message.message
                assert isinstance(jsonrpc_request.root, JSONRPCRequest)

                # Verify no metadata is passed when extra_headers is None
                assert session_message.metadata is None

                method = jsonrpc_request.root.method

                # Send appropriate response based on method
                if method == "logging/setLevel":
                    from mcp.types import EmptyResult

                    result = ServerResult(EmptyResult())
                elif method == "resources/list":
                    from mcp.types import ListResourcesResult

                    result = ServerResult(ListResourcesResult(resources=[]))
                elif method == "resources/templates/list":
                    from mcp.types import ListResourceTemplatesResult

                    result = ServerResult(ListResourceTemplatesResult(resourceTemplates=[]))
                elif method == "resources/read":
                    from mcp.types import ReadResourceResult

                    result = ServerResult(ReadResourceResult(contents=[]))
                elif method in ["resources/subscribe", "resources/unsubscribe"]:
                    from mcp.types import EmptyResult

                    result = ServerResult(EmptyResult())
                elif method == "prompts/list":
                    from mcp.types import ListPromptsResult

                    result = ServerResult(ListPromptsResult(prompts=[]))
                elif method == "prompts/get":
                    from mcp.types import GetPromptResult

                    result = ServerResult(GetPromptResult(messages=[]))
                elif method == "tools/list":
                    from mcp.types import ListToolsResult

                    result = ServerResult(ListToolsResult(tools=[]))
                else:
                    continue

                await server_to_client_send.send(
                    SessionMessage(
                        JSONRPCMessage(
                            JSONRPCResponse(
                                jsonrpc="2.0",
                                id=jsonrpc_request.root.id,
                                result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                            )
                        )
                    )
                )

            except anyio.EndOfStream:
                break

        server_to_client_send.close()

    async with (
        ClientSession(server_to_client_receive, client_to_server_send) as session,
        anyio.create_task_group() as tg,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        tg.start_soon(mock_server)
        await session.initialize()

        # Test all methods without extra_headers
        await session.set_logging_level("info")
        await session.list_resources()
        await session.list_resource_templates()
        from pydantic import AnyUrl

        test_uri = AnyUrl("file://test.txt")
        await session.read_resource(test_uri)
        await session.subscribe_resource(test_uri)
        await session.unsubscribe_resource(test_uri)
        await session.list_prompts()
        await session.get_prompt("test_prompt")
        await session.list_tools()


@pytest.mark.anyio
async def test_per_request_headers_take_precedence_over_connection_headers():
    """Test that per-request headers override connection-level headers when passed to metadata."""
    from mcp.types import EmptyResult

    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](5)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](5)

    # Track captured metadata from the session layer
    captured_metadata: list[ClientMessageMetadata] = []

    async def mock_server():
        # Handle initialization
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

        # Handle the test request
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        assert jsonrpc_request.root.method == "logging/setLevel"

        # Capture the metadata that was passed with the request
        if isinstance(session_message.metadata, ClientMessageMetadata):
            captured_metadata.append(session_message.metadata)

        # Send response
        await server_to_client_send.send(
            SessionMessage(
                JSONRPCMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.root.id,
                        result=ServerResult(EmptyResult()).model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )
        server_to_client_send.close()

    async with (
        ClientSession(server_to_client_receive, client_to_server_send) as session,
        anyio.create_task_group() as tg,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        tg.start_soon(mock_server)
        await session.initialize()

        # Per-request headers that demonstrate the functionality
        per_request_headers = {
            "Authorization": "Bearer per-request-token",
            "X-Request-ID": "req-456",
            "X-Environment": "staging",
        }

        # Make request with per-request headers
        await session.set_logging_level("debug", extra_headers=per_request_headers)

        # Verify metadata was captured and contains our headers
        assert len(captured_metadata) == 1
        metadata = captured_metadata[0]
        assert metadata is not None
        assert isinstance(metadata, ClientMessageMetadata)
        assert metadata.extra_headers == per_request_headers
