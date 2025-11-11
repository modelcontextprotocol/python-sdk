from typing import Any

import anyio
import pytest

import mcp.types as types
from mcp.client.session import DEFAULT_CLIENT_INFO, ClientSession
from mcp.shared.context import RequestContext
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    CallToolResult,
    ClientNotification,
    ClientRequest,
    Implementation,
    InitializedNotification,
    InitializeRequest,
    InitializeResult,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ServerCapabilities,
    ServerResult,
    TextContent,
)


@pytest.mark.anyio
async def test_client_session_initialize():
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    initialized_notification = None
    result = None

    async def mock_server():
        nonlocal initialized_notification

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
                capabilities=ServerCapabilities(
                    logging=None,
                    resources=None,
                    tools=None,
                    experimental=None,
                    prompts=None,
                ),
                serverInfo=Implementation(name="mock-server", version="0.1.0"),
                instructions="The server instructions.",
            )
        )

        async with server_to_client_send:
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
            session_notification = await client_to_server_receive.receive()
            jsonrpc_notification = session_notification.message
            assert isinstance(jsonrpc_notification.root, JSONRPCNotification)
            initialized_notification = ClientNotification.model_validate(
                jsonrpc_notification.model_dump(by_alias=True, mode="json", exclude_none=True)
            )

    # Create a message handler to catch exceptions
    async def message_handler(  # pragma: no cover
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):
            raise message

    async with (
        ClientSession(
            server_to_client_receive,
            client_to_server_send,
            message_handler=message_handler,
        ) as session,
        anyio.create_task_group() as tg,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        tg.start_soon(mock_server)
        result = await session.initialize()

    # Assert the result
    assert isinstance(result, InitializeResult)
    assert result.protocolVersion == LATEST_PROTOCOL_VERSION
    assert isinstance(result.capabilities, ServerCapabilities)
    assert result.serverInfo == Implementation(name="mock-server", version="0.1.0")
    assert result.instructions == "The server instructions."

    # Check that the client sent the initialized notification
    assert initialized_notification
    assert isinstance(initialized_notification.root, InitializedNotification)


@pytest.mark.anyio
async def test_client_session_custom_client_info():
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    custom_client_info = Implementation(name="test-client", version="1.2.3")
    received_client_info = None

    async def mock_server():
        nonlocal received_client_info

        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        request = ClientRequest.model_validate(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request.root, InitializeRequest)
        received_client_info = request.root.params.clientInfo

        result = ServerResult(
            InitializeResult(
                protocolVersion=LATEST_PROTOCOL_VERSION,
                capabilities=ServerCapabilities(),
                serverInfo=Implementation(name="mock-server", version="0.1.0"),
            )
        )

        async with server_to_client_send:
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

    async with (
        ClientSession(
            server_to_client_receive,
            client_to_server_send,
            client_info=custom_client_info,
        ) as session,
        anyio.create_task_group() as tg,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        tg.start_soon(mock_server)
        await session.initialize()

    # Assert that the custom client info was sent
    assert received_client_info == custom_client_info


@pytest.mark.anyio
async def test_client_session_default_client_info():
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    received_client_info = None

    async def mock_server():
        nonlocal received_client_info

        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        request = ClientRequest.model_validate(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request.root, InitializeRequest)
        received_client_info = request.root.params.clientInfo

        result = ServerResult(
            InitializeResult(
                protocolVersion=LATEST_PROTOCOL_VERSION,
                capabilities=ServerCapabilities(),
                serverInfo=Implementation(name="mock-server", version="0.1.0"),
            )
        )

        async with server_to_client_send:
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

    # Assert that the default client info was sent
    assert received_client_info == DEFAULT_CLIENT_INFO


@pytest.mark.anyio
async def test_client_session_version_negotiation_success():
    """Test successful version negotiation with supported version"""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)
    result = None

    async def mock_server():
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        request = ClientRequest.model_validate(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request.root, InitializeRequest)

        # Verify client sent the latest protocol version
        assert request.root.params.protocolVersion == LATEST_PROTOCOL_VERSION

        # Server responds with a supported older version
        result = ServerResult(
            InitializeResult(
                protocolVersion="2024-11-05",
                capabilities=ServerCapabilities(),
                serverInfo=Implementation(name="mock-server", version="0.1.0"),
            )
        )

        async with server_to_client_send:
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
        result = await session.initialize()

    # Assert the result with negotiated version
    assert isinstance(result, InitializeResult)
    assert result.protocolVersion == "2024-11-05"
    assert result.protocolVersion in SUPPORTED_PROTOCOL_VERSIONS


@pytest.mark.anyio
async def test_client_session_version_negotiation_failure():
    """Test version negotiation failure with unsupported version"""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    async def mock_server():
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        request = ClientRequest.model_validate(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request.root, InitializeRequest)

        # Server responds with an unsupported version
        result = ServerResult(
            InitializeResult(
                protocolVersion="2020-01-01",  # Unsupported old version
                capabilities=ServerCapabilities(),
                serverInfo=Implementation(name="mock-server", version="0.1.0"),
            )
        )

        async with server_to_client_send:
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

        # Should raise RuntimeError for unsupported version
        with pytest.raises(RuntimeError, match="Unsupported protocol version"):
            await session.initialize()


@pytest.mark.anyio
async def test_client_capabilities_default():
    """Test that client capabilities are properly set with default callbacks"""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    received_capabilities = None

    async def mock_server():
        nonlocal received_capabilities

        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        request = ClientRequest.model_validate(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request.root, InitializeRequest)
        received_capabilities = request.root.params.capabilities

        result = ServerResult(
            InitializeResult(
                protocolVersion=LATEST_PROTOCOL_VERSION,
                capabilities=ServerCapabilities(),
                serverInfo=Implementation(name="mock-server", version="0.1.0"),
            )
        )

        async with server_to_client_send:
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

    # Assert that capabilities are properly set with defaults
    assert received_capabilities is not None
    assert received_capabilities.sampling is None  # No custom sampling callback
    assert received_capabilities.roots is None  # No custom list_roots callback


@pytest.mark.anyio
async def test_client_capabilities_with_custom_callbacks():
    """Test that client capabilities are properly set with custom callbacks"""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    received_capabilities = None

    async def custom_sampling_callback(  # pragma: no cover
        context: RequestContext["ClientSession", Any],
        params: types.CreateMessageRequestParams,
    ) -> types.CreateMessageResult | types.ErrorData:
        return types.CreateMessageResult(
            role="assistant",
            content=types.TextContent(type="text", text="test"),
            model="test-model",
        )

    async def custom_list_roots_callback(  # pragma: no cover
        context: RequestContext["ClientSession", Any],
    ) -> types.ListRootsResult | types.ErrorData:
        return types.ListRootsResult(roots=[])

    async def mock_server():
        nonlocal received_capabilities

        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)
        request = ClientRequest.model_validate(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request.root, InitializeRequest)
        received_capabilities = request.root.params.capabilities

        result = ServerResult(
            InitializeResult(
                protocolVersion=LATEST_PROTOCOL_VERSION,
                capabilities=ServerCapabilities(),
                serverInfo=Implementation(name="mock-server", version="0.1.0"),
            )
        )

        async with server_to_client_send:
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

    async with (
        ClientSession(
            server_to_client_receive,
            client_to_server_send,
            sampling_callback=custom_sampling_callback,
            list_roots_callback=custom_list_roots_callback,
        ) as session,
        anyio.create_task_group() as tg,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        tg.start_soon(mock_server)
        await session.initialize()

    # Assert that capabilities are properly set with custom callbacks
    assert received_capabilities is not None
    # Custom sampling callback provided
    assert received_capabilities.sampling is not None
    assert isinstance(received_capabilities.sampling, types.SamplingCapability)
    # Custom list_roots callback provided
    assert received_capabilities.roots is not None
    assert isinstance(received_capabilities.roots, types.RootsCapability)
    # Should be True for custom callback
    assert received_capabilities.roots.listChanged is True


@pytest.mark.anyio
async def test_get_server_capabilities():
    """Test that get_server_capabilities returns None before init and capabilities after"""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    expected_capabilities = ServerCapabilities(
        logging=types.LoggingCapability(),
        prompts=types.PromptsCapability(listChanged=True),
        resources=types.ResourcesCapability(subscribe=True, listChanged=True),
        tools=types.ToolsCapability(listChanged=False),
    )

    async def mock_server():
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
                capabilities=expected_capabilities,
                serverInfo=Implementation(name="mock-server", version="0.1.0"),
            )
        )

        async with server_to_client_send:
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
            await client_to_server_receive.receive()

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
        assert session.get_server_capabilities() is None

        tg.start_soon(mock_server)
        await session.initialize()

        capabilities = session.get_server_capabilities()
        assert capabilities is not None
        assert capabilities == expected_capabilities
        assert capabilities.logging is not None
        assert capabilities.prompts is not None
        assert capabilities.prompts.listChanged is True
        assert capabilities.resources is not None
        assert capabilities.resources.subscribe is True
        assert capabilities.tools is not None
        assert capabilities.tools.listChanged is False


@pytest.mark.anyio
@pytest.mark.parametrize(argnames="meta", argvalues=[None, {"toolMeta": "value"}])
async def test_client_tool_call_with_meta(meta: dict[str, Any] | None):
    """Test that client tool call requests can include metadata"""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    mocked_tool = types.Tool(name="sample_tool", inputSchema={})

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

        if meta is not None:
            assert jsonrpc_request.root.params
            assert "_meta" in jsonrpc_request.root.params
            assert jsonrpc_request.root.params["_meta"] == meta

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
        # The client requires this step to validate the tool output schema
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request.root, JSONRPCRequest)

        assert jsonrpc_request.root.method == "tools/list"

        result = types.ListToolsResult(tools=[mocked_tool])

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

        await session.call_tool(name=mocked_tool.name, arguments={"foo": "bar"}, meta=meta)
