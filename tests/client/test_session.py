from __future__ import annotations

import anyio
import pytest

from mcp import types
from mcp.client.session import DEFAULT_CLIENT_INFO, ClientSession
from mcp.shared._context import RequestContext
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    CallToolResult,
    Implementation,
    InitializedNotification,
    InitializeRequest,
    InitializeResult,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    RequestParamsMeta,
    ServerCapabilities,
    TextContent,
    client_notification_adapter,
    client_request_adapter,
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
        assert isinstance(jsonrpc_request, JSONRPCRequest)
        request = client_request_adapter.validate_python(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request, InitializeRequest)

        result = InitializeResult(
            protocol_version=LATEST_PROTOCOL_VERSION,
            capabilities=ServerCapabilities(
                logging=None,
                resources=None,
                tools=None,
                experimental=None,
                prompts=None,
            ),
            server_info=Implementation(name="mock-server", version="0.1.0"),
            instructions="The server instructions.",
        )

        async with server_to_client_send:
            await server_to_client_send.send(
                SessionMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.id,
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
            session_notification = await client_to_server_receive.receive()
            jsonrpc_notification = session_notification.message
            assert isinstance(jsonrpc_notification, JSONRPCNotification)
            initialized_notification = client_notification_adapter.validate_python(
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
    assert result.protocol_version == LATEST_PROTOCOL_VERSION
    assert isinstance(result.capabilities, ServerCapabilities)
    assert result.server_info == Implementation(name="mock-server", version="0.1.0")
    assert result.instructions == "The server instructions."

    # Check that the client sent the initialized notification
    assert initialized_notification
    assert isinstance(initialized_notification, InitializedNotification)


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
        assert isinstance(jsonrpc_request, JSONRPCRequest)
        request = client_request_adapter.validate_python(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request, InitializeRequest)
        received_client_info = request.params.client_info

        result = InitializeResult(
            protocol_version=LATEST_PROTOCOL_VERSION,
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="mock-server", version="0.1.0"),
        )

        async with server_to_client_send:
            await server_to_client_send.send(
                SessionMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.id,
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
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
        assert isinstance(jsonrpc_request, JSONRPCRequest)
        request = client_request_adapter.validate_python(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request, InitializeRequest)
        received_client_info = request.params.client_info

        result = InitializeResult(
            protocol_version=LATEST_PROTOCOL_VERSION,
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="mock-server", version="0.1.0"),
        )

        async with server_to_client_send:
            await server_to_client_send.send(
                SessionMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.id,
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
            # Receive initialized notification
            await client_to_server_receive.receive()

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
        assert isinstance(jsonrpc_request, JSONRPCRequest)
        request = client_request_adapter.validate_python(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request, InitializeRequest)

        # Verify client sent the latest protocol version
        assert request.params.protocol_version == LATEST_PROTOCOL_VERSION

        # Server responds with a supported older version
        result = InitializeResult(
            protocol_version="2024-11-05",
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="mock-server", version="0.1.0"),
        )

        async with server_to_client_send:
            await server_to_client_send.send(
                SessionMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.id,
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
            # Receive initialized notification
            await client_to_server_receive.receive()

    async with (
        ClientSession(server_to_client_receive, client_to_server_send) as session,
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
    assert result.protocol_version == "2024-11-05"
    assert result.protocol_version in SUPPORTED_PROTOCOL_VERSIONS


@pytest.mark.anyio
async def test_client_session_version_negotiation_failure():
    """Test version negotiation failure with unsupported version"""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    async def mock_server():
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request, JSONRPCRequest)
        request = client_request_adapter.validate_python(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request, InitializeRequest)

        # Server responds with an unsupported version
        result = InitializeResult(
            protocol_version="2020-01-01",  # Unsupported old version
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="mock-server", version="0.1.0"),
        )

        async with server_to_client_send:
            await server_to_client_send.send(
                SessionMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.id,
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )

    async with (
        ClientSession(server_to_client_receive, client_to_server_send) as session,
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
        assert isinstance(jsonrpc_request, JSONRPCRequest)
        request = client_request_adapter.validate_python(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request, InitializeRequest)
        received_capabilities = request.params.capabilities

        result = InitializeResult(
            protocol_version=LATEST_PROTOCOL_VERSION,
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="mock-server", version="0.1.0"),
        )

        async with server_to_client_send:
            await server_to_client_send.send(
                SessionMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.id,
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
            # Receive initialized notification
            await client_to_server_receive.receive()

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
        context: RequestContext[ClientSession],
        params: types.CreateMessageRequestParams,
    ) -> types.CreateMessageResult | types.ErrorData:
        return types.CreateMessageResult(
            role="assistant",
            content=types.TextContent(type="text", text="test"),
            model="test-model",
        )

    async def custom_list_roots_callback(  # pragma: no cover
        context: RequestContext[ClientSession],
    ) -> types.ListRootsResult | types.ErrorData:
        return types.ListRootsResult(roots=[])

    async def mock_server():
        nonlocal received_capabilities

        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request, JSONRPCRequest)
        request = client_request_adapter.validate_python(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request, InitializeRequest)
        received_capabilities = request.params.capabilities

        result = InitializeResult(
            protocol_version=LATEST_PROTOCOL_VERSION,
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="mock-server", version="0.1.0"),
        )

        async with server_to_client_send:
            await server_to_client_send.send(
                SessionMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.id,
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
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
    # Default sampling capabilities (no tools)
    assert received_capabilities.sampling.tools is None
    # Custom list_roots callback provided
    assert received_capabilities.roots is not None
    assert isinstance(received_capabilities.roots, types.RootsCapability)
    # Should be True for custom callback
    assert received_capabilities.roots.list_changed is True


@pytest.mark.anyio
async def test_client_capabilities_with_sampling_tools():
    """Test that sampling capabilities with tools are properly advertised"""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    received_capabilities = None

    async def custom_sampling_callback(  # pragma: no cover
        context: RequestContext[ClientSession],
        params: types.CreateMessageRequestParams,
    ) -> types.CreateMessageResult | types.ErrorData:
        return types.CreateMessageResult(
            role="assistant",
            content=types.TextContent(type="text", text="test"),
            model="test-model",
        )

    async def mock_server():
        nonlocal received_capabilities

        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request, JSONRPCRequest)
        request = client_request_adapter.validate_python(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request, InitializeRequest)
        received_capabilities = request.params.capabilities

        result = InitializeResult(
            protocol_version=LATEST_PROTOCOL_VERSION,
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="mock-server", version="0.1.0"),
        )

        async with server_to_client_send:
            await server_to_client_send.send(
                SessionMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.id,
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
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
            sampling_capabilities=types.SamplingCapability(tools=types.SamplingToolsCapability()),
        ) as session,
        anyio.create_task_group() as tg,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        tg.start_soon(mock_server)
        await session.initialize()

    # Assert that sampling capabilities with tools are properly advertised
    assert received_capabilities is not None
    assert received_capabilities.sampling is not None
    assert isinstance(received_capabilities.sampling, types.SamplingCapability)
    # Tools capability should be present
    assert received_capabilities.sampling.tools is not None
    assert isinstance(received_capabilities.sampling.tools, types.SamplingToolsCapability)


@pytest.mark.anyio
async def test_get_server_capabilities():
    """Test that get_server_capabilities returns None before init and capabilities after"""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    expected_capabilities = ServerCapabilities(
        logging=types.LoggingCapability(),
        prompts=types.PromptsCapability(list_changed=True),
        resources=types.ResourcesCapability(subscribe=True, list_changed=True),
        tools=types.ToolsCapability(list_changed=False),
    )

    async def mock_server():
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request, JSONRPCRequest)
        request = client_request_adapter.validate_python(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request, InitializeRequest)

        result = InitializeResult(
            protocol_version=LATEST_PROTOCOL_VERSION,
            capabilities=expected_capabilities,
            server_info=Implementation(name="mock-server", version="0.1.0"),
        )

        async with server_to_client_send:
            await server_to_client_send.send(
                SessionMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.id,
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
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
        assert capabilities.prompts.list_changed is True
        assert capabilities.resources is not None
        assert capabilities.resources.subscribe is True
        assert capabilities.tools is not None
        assert capabilities.tools.list_changed is False


@pytest.mark.anyio
@pytest.mark.parametrize(argnames="meta", argvalues=[None, {"toolMeta": "value"}])
async def test_client_tool_call_with_meta(meta: RequestParamsMeta | None):
    """Test that client tool call requests can include metadata"""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    mocked_tool = types.Tool(name="sample_tool", input_schema={})

    async def mock_server():
        # Receive initialization request from client
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request, JSONRPCRequest)
        request = client_request_adapter.validate_python(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request, InitializeRequest)

        result = InitializeResult(
            protocol_version=LATEST_PROTOCOL_VERSION,
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="mock-server", version="0.1.0"),
        )

        # Answer initialization request
        await server_to_client_send.send(
            SessionMessage(
                JSONRPCResponse(
                    jsonrpc="2.0",
                    id=jsonrpc_request.id,
                    result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                )
            )
        )

        # Receive initialized notification
        await client_to_server_receive.receive()

        # Wait for the client to send a 'tools/call' request
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request, JSONRPCRequest)

        assert jsonrpc_request.method == "tools/call"

        if meta is not None:
            assert jsonrpc_request.params
            assert "_meta" in jsonrpc_request.params
            assert jsonrpc_request.params["_meta"] == meta

        result = CallToolResult(content=[TextContent(type="text", text="Called successfully")], is_error=False)

        # Send the tools/call result
        await server_to_client_send.send(
            SessionMessage(
                JSONRPCResponse(
                    jsonrpc="2.0",
                    id=jsonrpc_request.id,
                    result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                )
            )
        )

        # Wait for the tools/list request from the client
        # The client requires this step to validate the tool output schema
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request, JSONRPCRequest)

        assert jsonrpc_request.method == "tools/list"

        result = types.ListToolsResult(tools=[mocked_tool])

        await server_to_client_send.send(
            SessionMessage(
                JSONRPCResponse(
                    jsonrpc="2.0",
                    id=jsonrpc_request.id,
                    result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
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

        await session.call_tool(name=mocked_tool.name, arguments={"foo": "bar"}, meta=meta)


@pytest.mark.anyio
async def test_client_session_get_state():
    """Test that get_session_state() returns a valid SessionState."""
    from mcp.shared.session_state import SessionState

    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    async def mock_server():
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request, JSONRPCRequest)

        result = InitializeResult(
            protocol_version=LATEST_PROTOCOL_VERSION,
            capabilities=ServerCapabilities(
                logging=None,
                resources=None,
                tools=None,
                experimental=None,
                prompts=None,
            ),
            server_info=Implementation(name="mock-server", version="0.1.0"),
        )

        async with server_to_client_send:
            await server_to_client_send.send(
                SessionMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.id,
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
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
        tg.start_soon(mock_server)

        # Initialize the session
        await session.initialize()

        # Get session state
        state = session.get_session_state()

        # Verify the state
        assert isinstance(state, SessionState)
        assert state.session_id is not None
        assert state.protocol_version == LATEST_PROTOCOL_VERSION
        assert state.next_request_id == 1  # After initialize request
        assert state.server_capabilities is not None
        assert state.server_info is not None
        assert state.initialized_sent is True

        # Verify it's serializable
        json_str = state.model_dump_json()
        assert json_str is not None


@pytest.mark.anyio
async def test_client_session_from_state():
    """Test that from_session_state() creates a valid session."""
    from mcp.shared.session_state import SessionState

    # Create a session state
    state = SessionState(
        session_id="test-session-from-state",
        protocol_version=LATEST_PROTOCOL_VERSION,
        next_request_id=5,
        server_capabilities={
            "tools": {},
            "resources": {},
            "prompts": None,
            "logging": None,
            "experimental": None,
        },
        server_info={"name": "test-server", "version": "1.0.0"},
        initialized_sent=True,
    )

    # Create streams
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    # Create session from state
    session = ClientSession.from_session_state(
        state,
        server_to_client_receive,
        client_to_server_send,
    )

    # Verify the session was created with the correct state
    assert session._session_id == "test-session-from-state"
    assert session._request_id == 5  # Continues from saved state
    assert session._server_capabilities is not None
    assert session._initialized_sent is True
    assert session._server_info is not None
    assert session._server_info.name == "test-server"
    assert session._server_info.version == "1.0.0"

    # Clean up streams
    async with (
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        pass


@pytest.mark.anyio
async def test_client_session_state_roundtrip():
    """Test that session state can be serialized and restored."""
    from mcp.shared.session_state import SessionState

    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    async def mock_server():
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request, JSONRPCRequest)

        result = InitializeResult(
            protocol_version=LATEST_PROTOCOL_VERSION,
            capabilities=ServerCapabilities(
                logging=None,
                resources=None,
                tools=None,
                experimental=None,
                prompts=None,
            ),
            server_info=Implementation(name="mock-server", version="0.1.0"),
        )

        async with server_to_client_send:
            await server_to_client_send.send(
                SessionMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=jsonrpc_request.id,
                        result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
            await client_to_server_receive.receive()

    async with (
        ClientSession(
            server_to_client_receive,
            client_to_server_send,
        ) as original_session,
        anyio.create_task_group() as tg,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        tg.start_soon(mock_server)

        # Initialize the session
        await original_session.initialize()

        # Extract state
        original_state = original_session.get_session_state()

        # Verify it can be serialized to JSON
        json_str = original_state.model_dump_json()

        # Verify it can be deserialized from JSON
        restored_state = SessionState.model_validate_json(json_str)

        # Verify all fields match
        assert restored_state.session_id == original_state.session_id
        assert restored_state.protocol_version == original_state.protocol_version
        assert restored_state.next_request_id == original_state.next_request_id
        assert restored_state.server_capabilities == original_state.server_capabilities
        assert restored_state.server_info == original_state.server_info
        assert restored_state.initialized_sent == original_state.initialized_sent
