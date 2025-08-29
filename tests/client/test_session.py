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
    async def message_handler(
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

    async def custom_sampling_callback(
        context: RequestContext["ClientSession", Any],
        params: types.CreateMessageRequestParams,
    ) -> types.CreateMessageResult | types.ErrorData:
        return types.CreateMessageResult(
            role="assistant",
            content=types.TextContent(type="text", text="test"),
            model="test-model",
        )

    async def custom_list_roots_callback(
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
    assert received_capabilities.sampling is not None  # Custom sampling callback provided
    assert isinstance(received_capabilities.sampling, types.SamplingCapability)
    assert received_capabilities.roots is not None  # Custom list_roots callback provided
    assert isinstance(received_capabilities.roots, types.RootsCapability)
    assert received_capabilities.roots.listChanged is True  # Should be True for custom callback
