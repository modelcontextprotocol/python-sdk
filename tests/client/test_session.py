from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, cast

import anyio
import anyio.abc
import anyio.streams.memory
import mcp_types as types
import pytest
from mcp_types import (
    CONNECTION_CLOSED,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION_META_KEY,
    REQUEST_TIMEOUT,
    UNSUPPORTED_PROTOCOL_VERSION,
    CallToolResult,
    Implementation,
    InitializedNotification,
    InitializeRequest,
    InitializeResult,
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    RequestParamsMeta,
    ServerCapabilities,
    TextContent,
    client_notification_adapter,
    client_request_adapter,
)
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS, LATEST_HANDSHAKE_VERSION
from pydantic import FileUrl, ValidationError

from mcp import MCPError
from mcp.client import ClientRequestContext
from mcp.client.client import Client
from mcp.client.session import DEFAULT_CLIENT_INFO, ClientSession
from mcp.server import Server, ServerRequestContext
from mcp.shared.direct_dispatcher import create_direct_dispatcher_pair
from mcp.shared.dispatcher import CallOptions, DispatchContext, OnNotify, OnRequest
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.shared.transport_context import TransportContext

_SendToClient = anyio.streams.memory.MemoryObjectSendStream[SessionMessage | Exception]
_RecvFromClient = anyio.streams.memory.MemoryObjectReceiveStream[SessionMessage]


@asynccontextmanager
async def raw_client_session(
    **kwargs: Any,
) -> AsyncIterator[tuple[ClientSession, _SendToClient, _RecvFromClient]]:
    """Yield `(session, send_to_client, recv_from_client)` with the receive loop running.

    `send_to_client` accepts `SessionMessage | Exception` so tests can inject
    transport-level exceptions. No initialize handshake is performed.
    """
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](32)
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage](32)
    async with ClientSession(s2c_recv, c2s_send, **kwargs) as session:
        try:
            with anyio.fail_after(5):
                yield session, s2c_send, c2s_recv
        finally:
            s2c_send.close()
            c2s_recv.close()


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
            protocol_version=LATEST_HANDSHAKE_VERSION,
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
    assert result.protocol_version == LATEST_HANDSHAKE_VERSION
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
            protocol_version=LATEST_HANDSHAKE_VERSION,
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
            protocol_version=LATEST_HANDSHAKE_VERSION,
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

        # Verify client offers the newest handshake protocol version
        assert request.params.protocol_version == LATEST_HANDSHAKE_VERSION

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
    assert result.protocol_version in HANDSHAKE_PROTOCOL_VERSIONS


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
            protocol_version=LATEST_HANDSHAKE_VERSION,
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
        context: ClientRequestContext,
        params: types.CreateMessageRequestParams,
    ) -> types.CreateMessageResult | types.ErrorData:
        return types.CreateMessageResult(
            role="assistant",
            content=types.TextContent(type="text", text="test"),
            model="test-model",
        )

    async def custom_list_roots_callback(  # pragma: no cover
        context: ClientRequestContext,
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
            protocol_version=LATEST_HANDSHAKE_VERSION,
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
        context: ClientRequestContext,
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
            protocol_version=LATEST_HANDSHAKE_VERSION,
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
async def test_initialize_result():
    """Test that initialize_result is None before init and contains the full result after."""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    expected_capabilities = ServerCapabilities(
        logging=types.LoggingCapability(),
        prompts=types.PromptsCapability(list_changed=True),
        resources=types.ResourcesCapability(subscribe=True, list_changed=True),
        tools=types.ToolsCapability(list_changed=False),
    )
    expected_server_info = Implementation(name="mock-server", version="0.1.0")
    expected_instructions = "Use the tools wisely."

    async def mock_server():
        session_message = await client_to_server_receive.receive()
        jsonrpc_request = session_message.message
        assert isinstance(jsonrpc_request, JSONRPCRequest)
        request = client_request_adapter.validate_python(
            jsonrpc_request.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert isinstance(request, InitializeRequest)

        result = InitializeResult(
            protocol_version=LATEST_HANDSHAKE_VERSION,
            capabilities=expected_capabilities,
            server_info=expected_server_info,
            instructions=expected_instructions,
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
        assert session.initialize_result is None

        tg.start_soon(mock_server)
        await session.initialize()

        result = session.initialize_result
        assert result is not None
        assert result.server_info == expected_server_info
        assert result.capabilities == expected_capabilities
        assert result.instructions == expected_instructions
        assert result.protocol_version == LATEST_HANDSHAKE_VERSION
        # Era-neutral accessors are populated from the InitializeResult.
        assert session.server_info == expected_server_info
        assert session.server_capabilities == expected_capabilities
        assert session.instructions == expected_instructions
        assert session.protocol_version == LATEST_HANDSHAKE_VERSION


@pytest.mark.anyio
@pytest.mark.parametrize(argnames="meta", argvalues=[None, {"toolMeta": "value"}])
async def test_client_tool_call_with_meta(meta: RequestParamsMeta | None):
    """Test that client tool call requests can include metadata"""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    mocked_tool = types.Tool(name="sample_tool", input_schema={"type": "object"})

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
            protocol_version=LATEST_HANDSHAKE_VERSION,
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
async def test_receive_loop_answers_malformed_inbound_request_with_invalid_params():
    """A request that fails ServerRequest validation gets an INVALID_PARAMS error response."""
    async with raw_client_session() as (_session, to_client, from_client):
        await to_client.send(
            SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=7, method="sampling/createMessage", params={"broken": 1}))
        )
        out = await from_client.receive()
    assert isinstance(out.message, JSONRPCError)
    assert out.message.id == 7
    assert out.message.error.code == INVALID_PARAMS


@pytest.mark.anyio
async def test_receive_loop_answers_unknown_request_method_with_method_not_found():
    """An unknown request method is answered with METHOD_NOT_FOUND, not INVALID_PARAMS (spec-mandated)."""
    async with raw_client_session() as (_session, to_client, from_client):
        await to_client.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=7, method="x/unknown")))
        out = await from_client.receive()
    assert isinstance(out.message, JSONRPCError)
    assert out.message.id == 7
    assert out.message.error == types.ErrorData(code=METHOD_NOT_FOUND, message="Method not found", data="x/unknown")


@pytest.mark.anyio
async def test_receive_loop_drops_unknown_notification_method_without_response():
    """An unknown notification method is dropped silently: JSON-RPC forbids responses to notifications."""
    async with raw_client_session() as (_session, to_client, from_client):
        await to_client.send(SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="x/unknown")))
        # The answered follow-up ping proves no response was emitted and the loop survived.
        await to_client.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")))
        out = await from_client.receive()
    assert isinstance(out.message, JSONRPCResponse)
    assert out.message.id == 1


def _set_negotiated_version(session: ClientSession, version: str) -> None:
    """Force `session.protocol_version` without running the handshake."""
    session.adopt(
        InitializeResult(
            protocol_version=version,
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="mock-server", version="0.1.0"),
        )
    )


@pytest.mark.anyio
async def test_on_request_rejects_a_server_request_absent_at_the_negotiated_version():
    """`elicitation/create` does not exist at 2025-03-26: the version gate answers
    METHOD_NOT_FOUND instead of reaching the elicitation callback."""
    async with raw_client_session() as (session, to_client, from_client):
        _set_negotiated_version(session, "2025-03-26")
        await to_client.send(
            SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=1, method="elicitation/create", params={"message": "hi"}))
        )
        out = await from_client.receive()
    assert isinstance(out.message, JSONRPCError)
    assert out.message.error.code == METHOD_NOT_FOUND
    assert out.message.error.data == "elicitation/create"


@pytest.mark.anyio
async def test_on_request_validates_the_callback_result_against_the_surface_schema():
    """A surface-valid callback result reaches the wire as the dump dict unchanged."""

    async def sampling(
        ctx: ClientRequestContext, params: types.CreateMessageRequestParams
    ) -> types.CreateMessageResult:
        return types.CreateMessageResult(role="assistant", content=types.TextContent(type="text", text="hi"), model="m")

    request_params = types.CreateMessageRequestParams(
        messages=[types.SamplingMessage(role="user", content=types.TextContent(type="text", text="q"))],
        max_tokens=10,
    ).model_dump(by_alias=True, mode="json", exclude_none=True)
    async with raw_client_session(sampling_callback=sampling) as (_session, to_client, from_client):
        await to_client.send(
            SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=2, method="sampling/createMessage", params=request_params))
        )
        out = await from_client.receive()
    assert isinstance(out.message, JSONRPCResponse)
    assert out.message.result == {"role": "assistant", "content": {"type": "text", "text": "hi"}, "model": "m"}


@pytest.mark.anyio
async def test_on_request_callback_returning_a_surface_invalid_result_is_internal_error(
    caplog: pytest.LogCaptureFixture,
):
    """A callback result the surface schema rejects is answered with INTERNAL_ERROR.
    `EmptyResult` is a `ClientResult` arm so the union accepts it, but `roots/list`
    requires a `roots` array."""

    async def list_roots(ctx: ClientRequestContext) -> types.ListRootsResult | types.ErrorData:
        return cast("types.ListRootsResult", types.EmptyResult())

    async with raw_client_session(list_roots_callback=list_roots) as (_session, to_client, from_client):
        await to_client.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=3, method="roots/list")))
        out = await from_client.receive()
    assert isinstance(out.message, JSONRPCError)
    assert out.message.error.code == INTERNAL_ERROR
    assert out.message.error.message == "Client callback returned an invalid result"
    assert "client callback for 'roots/list' returned an invalid result" in caplog.text


@pytest.mark.anyio
async def test_on_notify_drops_a_server_notification_absent_at_the_negotiated_version(
    caplog: pytest.LogCaptureFixture,
):
    """`notifications/elicitation/complete` does not exist at 2025-06-18: it is
    debug-log-dropped without reaching `message_handler`."""
    seen: list[object] = []
    delivered = anyio.Event()

    async def handler(msg: object) -> None:
        seen.append(msg)
        delivered.set()

    with caplog.at_level("DEBUG", logger="client"):
        async with raw_client_session(message_handler=handler) as (session, to_client, _):
            _set_negotiated_version(session, "2025-06-18")
            await to_client.send(
                SessionMessage(
                    JSONRPCNotification(
                        jsonrpc="2.0", method="notifications/elicitation/complete", params={"elicitationId": "e1"}
                    )
                )
            )
            await to_client.send(
                SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/tools/list_changed"))
            )
            await delivered.wait()
    assert len(seen) == 1
    assert isinstance(seen[0], types.ToolListChangedNotification)
    assert "dropped 'notifications/elicitation/complete': not defined at 2025-06-18" in caplog.text


@pytest.mark.anyio
async def test_on_request_elicitation_with_loose_property_schema_reaches_the_callback():
    """Older python-sdk servers emit `anyOf` for `Optional` form fields; the
    inbound surface gate must let that through to the elicitation callback."""
    seen: list[types.ElicitRequestParams] = []

    async def elicitation(ctx: ClientRequestContext, params: types.ElicitRequestParams) -> types.ElicitResult:
        seen.append(params)
        return types.ElicitResult(action="accept", content={"x": 1})

    request_params = {
        "message": "m",
        "requestedSchema": {
            "type": "object",
            "properties": {"x": {"anyOf": [{"type": "integer"}, {"type": "null"}]}},
        },
    }
    async with raw_client_session(elicitation_callback=elicitation) as (_session, to_client, from_client):
        await to_client.send(
            SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=4, method="elicitation/create", params=request_params))
        )
        out = await from_client.receive()
    assert isinstance(out.message, JSONRPCResponse)
    assert out.message.result == {"action": "accept", "content": {"x": 1}}
    assert len(seen) == 1


@pytest.mark.anyio
async def test_send_request_validates_the_server_result_against_the_surface_schema():
    """A spec-method result that fails the per-version surface schema raises
    `ValidationError` even when the caller's `result_type` would accept it."""
    async with raw_client_session() as (session, to_client, from_client):
        async with anyio.create_task_group() as tg:

            async def call() -> None:
                with pytest.raises(ValidationError):
                    await session.send_request(types.ListToolsRequest(), types.EmptyResult)

            tg.start_soon(call)
            request = await from_client.receive()
            assert isinstance(request.message, JSONRPCRequest)
            await to_client.send(
                SessionMessage(JSONRPCResponse(jsonrpc="2.0", id=request.message.id, result={"tools": "nope"}))
            )


@pytest.mark.anyio
async def test_send_request_skips_the_surface_gate_when_method_absent_at_version():
    """Surface row absent for the negotiated version: gate is bypassed and only
    `result_type` validates."""
    async with raw_client_session() as (session, to_client, from_client):
        _set_negotiated_version(session, "2026-07-28")
        async with anyio.create_task_group() as tg:

            async def call() -> None:
                result = await session.send_request(types.PingRequest(), types.EmptyResult)
                assert isinstance(result, types.EmptyResult)

            tg.start_soon(call)
            request = await from_client.receive()
            assert isinstance(request.message, JSONRPCRequest)
            await to_client.send(SessionMessage(JSONRPCResponse(jsonrpc="2.0", id=request.message.id, result={})))


@pytest.mark.anyio
async def test_raising_sampling_callback_answers_with_code_zero():
    """A raising sampling callback is answered with code 0 and `str(exc)` (SDK-defined).
    Raw streams because the assertion is the outbound `JSONRPCError` envelope itself."""

    async def boom(ctx: object, params: object) -> types.CreateMessageResult:
        raise RuntimeError("sampling boom")

    params = types.CreateMessageRequestParams(
        messages=[types.SamplingMessage(role="user", content=types.TextContent(type="text", text="hi"))],
        max_tokens=10,
    ).model_dump(by_alias=True, mode="json", exclude_none=True)
    async with raw_client_session(sampling_callback=boom) as (_session, to_client, from_client):
        await to_client.send(
            SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=8, method="sampling/createMessage", params=params))
        )
        out = await from_client.receive()
    assert isinstance(out.message, JSONRPCError)
    assert out.message.error == types.ErrorData(code=0, message="sampling boom")


@pytest.mark.anyio
async def test_receive_loop_logs_and_drops_malformed_notification(caplog: pytest.LogCaptureFixture):
    """A malformed notification is warn-logged and dropped without reaching `message_handler` (SDK-defined).
    Scripted peer: the typed API cannot emit malformed params for a spec method."""
    seen: list[object] = []
    delivered = anyio.Event()

    async def handler(msg: object) -> None:
        seen.append(msg)
        delivered.set()

    async with raw_client_session(message_handler=handler) as (_session, to_client, _):
        await to_client.send(
            SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/progress", params={"broken": 1}))
        )
        # Follow with a valid notification so we know the loop is still alive.
        await to_client.send(
            SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/tools/list_changed"))
        )
        await delivered.wait()
    assert isinstance(seen[0], types.ToolListChangedNotification)
    assert "Failed to validate notification: notifications/progress" in caplog.text


@pytest.mark.anyio
async def test_raising_message_handler_on_transport_exception_costs_the_delivery_not_the_connection(
    caplog: pytest.LogCaptureFixture,
):
    """A `message_handler` that raises on a transport-level `Exception` item is contained: the
    failure is logged and the receive loop keeps serving (SDK-defined). Raw streams because
    only a transport can put an `Exception` item on the read stream."""
    seen: list[object] = []
    delivered = anyio.Event()

    async def handler(msg: object) -> None:
        seen.append(msg)
        delivered.set()
        # No checkpoint between set() and the containment log, so after wait() the log entry exists.
        raise RuntimeError("handler boom")

    async with raw_client_session(message_handler=handler) as (_session, to_client, from_client):
        exc = ValueError("bad bytes")
        await to_client.send(exc)
        await delivered.wait()
        await to_client.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=9, method="ping")))
        out = await from_client.receive()
    assert seen == [exc]
    assert isinstance(out.message, JSONRPCResponse)
    assert out.message.id == 9
    assert "message_handler raised on transport exception" in caplog.text


@pytest.mark.anyio
async def test_message_handler_awaiting_session_traffic_on_transport_exception_completes():
    """A `message_handler` that awaits session traffic on a transport `Exception` item completes:
    fault deliveries are spawned into the task group, not run inline in the read loop (SDK-defined).
    Raw streams because only a transport can put an `Exception` item on the read stream."""
    ponged = anyio.Event()

    # `session` resolves at call time, after the `as` clause binds it.
    async def handler(msg: object) -> None:
        assert isinstance(msg, Exception)
        await session.send_ping()
        ponged.set()

    async with raw_client_session(message_handler=handler) as (session, to_client, from_client):
        await to_client.send(ValueError("bad bytes"))
        # Serve the handler's ping like a transport would; inline delivery would deadlock here.
        out = await from_client.receive()
        assert isinstance(out.message, JSONRPCRequest)
        assert out.message.method == "ping"
        await to_client.send(SessionMessage(JSONRPCResponse(jsonrpc="2.0", id=out.message.id, result={})))
        await ponged.wait()


@pytest.mark.anyio
async def test_receive_loop_consumes_server_cancelled_without_reaching_message_handler():
    """A server-sent notifications/cancelled is swallowed, matching the pre-swap contract.

    The server dispatcher now emits this on sampling/elicitation timeout, but
    ClientSession has no in-flight tracking to act on it, so surfacing it would
    only break user handlers that exhaustively match ServerNotification.
    Scripted peer: the typed server API cannot emit a bare `notifications/cancelled`.
    """
    seen: list[object] = []
    delivered = anyio.Event()

    async def handler(msg: object) -> None:
        seen.append(msg)
        delivered.set()

    async with raw_client_session(message_handler=handler) as (_session, to_client, _):
        await to_client.send(
            SessionMessage(
                JSONRPCNotification(
                    jsonrpc="2.0", method="notifications/cancelled", params={"requestId": 1, "reason": "timed out"}
                )
            )
        )
        # Follow with a notification that does reach the handler so we can
        # assert ordering deterministically.
        await to_client.send(
            SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/tools/list_changed"))
        )
        await delivered.wait()
    assert len(seen) == 1
    assert isinstance(seen[0], types.ToolListChangedNotification)


@pytest.mark.anyio
async def test_request_timeout_zero_overrides_session_timeout():
    """`request_read_timeout_seconds=0` is a real per-request timeout (fail at the
    first checkpoint, `anyio.fail_after(0)` semantics), not a fall-through to the
    session-level timeout. The request is never answered, so falling back to the
    30s session timeout would trip the harness's 5s guard instead."""
    async with raw_client_session(read_timeout_seconds=30) as (session, _to_client, _from_client):
        with pytest.raises(MCPError) as exc_info:
            await session.send_request(types.PingRequest(), types.EmptyResult, request_read_timeout_seconds=0.0)
    assert exc_info.value.error.code == REQUEST_TIMEOUT


@pytest.mark.anyio
async def test_progress_notification_reaches_request_callback_and_message_handler():
    """A `notifications/progress` for an in-flight request reaches both the `progress_callback` and
    `message_handler` (SDK-defined). Scripted peer: the progress token must echo the wire request id."""
    updates: list[tuple[float, float | None, str | None]] = []
    teed: list[types.ProgressNotification] = []
    request_id: types.RequestId | None = None
    progressed = anyio.Event()
    delivered = anyio.Event()

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        updates.append((progress, total, message))
        progressed.set()

    async def handler(msg: object) -> None:
        # Only the progress notification is teed to the message handler here.
        assert isinstance(msg, types.ProgressNotification)
        teed.append(msg)
        delivered.set()

    async with raw_client_session(message_handler=handler) as (session, to_client, from_client):
        async with anyio.create_task_group() as tg:

            async def call() -> None:
                await session.send_request(types.PingRequest(), types.EmptyResult, progress_callback=on_progress)

            tg.start_soon(call)
            request = await from_client.receive()
            assert isinstance(request.message, JSONRPCRequest)
            request_id = request.message.id
            # The request id doubles as the progress token.
            params = {"progressToken": request_id, "progress": 0.5, "total": 1.0, "message": "halfway"}
            await to_client.send(
                SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/progress", params=params))
            )
            await progressed.wait()
            await delivered.wait()
            await to_client.send(SessionMessage(JSONRPCResponse(jsonrpc="2.0", id=request_id, result={})))
    assert updates == [(0.5, 1.0, "halfway")]
    assert request_id is not None
    assert len(teed) == 1
    assert teed[0].params == types.ProgressNotificationParams(
        progress_token=request_id, progress=0.5, total=1.0, message="halfway"
    )


@pytest.mark.anyio
async def test_dispatcher_keyword_runs_over_direct_dispatch():
    """A session built with dispatcher= works without a stream pair (in-process embedding)."""
    client_side, server_side = create_direct_dispatcher_pair()

    async def server_on_request(
        ctx: DispatchContext[TransportContext], method: str, params: dict[str, object] | None
    ) -> dict[str, object]:
        assert method == "ping"
        return {}

    notified: list[str] = []

    async def server_on_notify(
        ctx: DispatchContext[TransportContext], method: str, params: dict[str, object] | None
    ) -> None:
        notified.append(method)

    session = ClientSession(dispatcher=client_side)
    results: list[types.EmptyResult] = []
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            await tg.start(server_side.run, server_on_request, server_on_notify)
            async with session:
                results.append(await session.send_ping(meta=None))
                # Server-to-client: direct dispatch delivers ping with no params member (no _meta injection).
                assert await server_side.send_raw_request("ping", None) == {}
                await session.send_notification(types.RootsListChangedNotification())
            server_side.close()
    assert results == [types.EmptyResult()]
    assert notified == ["notifications/roots/list_changed"]


@pytest.mark.anyio
async def test_direct_dispatch_roots_list_reaches_callback_with_synthesized_request_id():
    """A server-initiated roots/list over dispatcher= reaches the registered callback and round-trips
    the result; the callback context carries an int request_id (SDK-defined: DirectDispatcher
    synthesizes ids)."""
    client_side, server_side = create_direct_dispatcher_pair()
    contexts: list[ClientRequestContext] = []

    async def list_roots(context: ClientRequestContext) -> types.ListRootsResult:
        contexts.append(context)
        return types.ListRootsResult(roots=[types.Root(uri=FileUrl("file:///workspace"))])

    async def server_on_request(
        ctx: DispatchContext[TransportContext], method: str, params: dict[str, object] | None
    ) -> dict[str, object]:
        raise NotImplementedError

    async def server_on_notify(
        ctx: DispatchContext[TransportContext], method: str, params: dict[str, object] | None
    ) -> None:
        raise NotImplementedError

    session = ClientSession(dispatcher=client_side, list_roots_callback=list_roots)
    result: dict[str, Any] | None = None
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            await tg.start(server_side.run, server_on_request, server_on_notify)
            async with session:
                result = await server_side.send_raw_request("roots/list", None)
            server_side.close()
    assert result == {"roots": [{"uri": "file:///workspace"}]}
    assert len(contexts) == 1
    assert isinstance(contexts[0].request_id, int)


@pytest.mark.anyio
async def test_raising_notification_callbacks_over_direct_dispatch_cost_only_that_delivery(
    caplog: pytest.LogCaptureFixture,
):
    """A raising `logging_callback` or `message_handler` is contained in the session, so the
    in-process peer's notify() returns normally and the session keeps serving requests
    (SDK-defined: DirectDispatcher awaits notification handlers inline in the peer's call).
    A raising `logging_callback` skips the `message_handler` tee for that notification."""
    client_side, server_side = create_direct_dispatcher_pair()
    teed: list[types.ServerNotification] = []

    async def logging_callback(params: types.LoggingMessageNotificationParams) -> None:
        raise ValueError("logging callback boom")

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        assert not isinstance(message, RequestResponder | Exception)
        teed.append(message)
        raise ValueError("message handler boom")

    async def server_on_request(
        ctx: DispatchContext[TransportContext], method: str, params: dict[str, object] | None
    ) -> dict[str, object]:
        assert method == "ping"
        return {}

    async def server_on_notify(
        ctx: DispatchContext[TransportContext], method: str, params: dict[str, object] | None
    ) -> None:
        raise NotImplementedError

    session = ClientSession(dispatcher=client_side, logging_callback=logging_callback, message_handler=message_handler)
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            await tg.start(server_side.run, server_on_request, server_on_notify)
            async with session:
                # logging_callback raises: notify() must return, and message_handler is skipped.
                await server_side.notify("notifications/message", {"level": "info", "data": "hello"})
                # message_handler raises: notify() must return.
                await server_side.notify("notifications/tools/list_changed", None)
                # The session still serves requests afterwards.
                assert await session.send_ping() == types.EmptyResult()
            server_side.close()
    assert [type(n) for n in teed] == [types.ToolListChangedNotification]
    assert caplog.text.count("notification callback for") == 2
    assert "notification callback for 'notifications/message' raised" in caplog.text
    assert "notification callback for 'notifications/tools/list_changed' raised" in caplog.text


@pytest.mark.anyio
async def test_dispatcher_keyword_send_request_before_enter_raises_runtimeerror():
    """The documented pre-enter RuntimeError holds for dispatcher= sessions too."""
    client_side, _server_side = create_direct_dispatcher_pair()
    session = ClientSession(dispatcher=client_side)
    with anyio.fail_after(5), pytest.raises(RuntimeError) as exc:
        await session.send_ping()
    assert str(exc.value) == "DirectDispatcher.send_raw_request called before run()"


@pytest.mark.anyio
async def test_dispatcher_keyword_send_request_after_exit_raises_connection_closed():
    """After __aexit__ a dispatcher= session raises MCPError(CONNECTION_CLOSED), matching the JSONRPC path."""
    client_side, server_side = create_direct_dispatcher_pair()

    async def server_on_request(
        ctx: DispatchContext[TransportContext], method: str, params: dict[str, object] | None
    ) -> dict[str, object]:
        assert method == "ping"
        return {}

    async def server_on_notify(
        ctx: DispatchContext[TransportContext], method: str, params: dict[str, object] | None
    ) -> None:
        raise NotImplementedError

    session = ClientSession(dispatcher=client_side)
    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            await tg.start(server_side.run, server_on_request, server_on_notify)
            async with session:
                assert await session.send_ping() == types.EmptyResult()
            with pytest.raises(MCPError) as exc:
                await session.send_ping()
            assert exc.value.error.code == CONNECTION_CLOSED
            server_side.close()


@pytest.mark.anyio
async def test_dispatcher_keyword_request_timeout_bounds_wait_for_never_run_peer():
    """request_read_timeout_seconds fires even when the peer dispatcher never started running."""
    client_side, _server_side = create_direct_dispatcher_pair()
    session = ClientSession(dispatcher=client_side)
    with anyio.fail_after(5):
        async with session:
            with pytest.raises(MCPError) as exc:
                await session.send_request(types.PingRequest(), types.EmptyResult, request_read_timeout_seconds=0.01)
            assert exc.value.error.code == REQUEST_TIMEOUT


def test_adopt_raises_when_no_mutual_modern_version_is_supported() -> None:
    """SDK-defined: ``adopt(DiscoverResult)`` picks the newest version both sides support; an
    empty intersection is unrecoverable and raises rather than installing a stamp."""
    client_d, _ = create_direct_dispatcher_pair()
    session = ClientSession(dispatcher=client_d)
    with pytest.raises(RuntimeError, match="No mutually supported modern protocol version"):
        session.adopt(
            types.DiscoverResult(
                supported_versions=["1999-01-01"],
                capabilities=types.ServerCapabilities(),
                server_info=types.Implementation(name="s", version="0"),
                result_type="complete",
                ttl_ms=0,
                cache_scope="public",
            )
        )
    assert session.protocol_version is None


@pytest.mark.anyio
async def test_initialize_opts_out_of_cancel_on_abandon_while_other_requests_leave_it_unset():
    """`send_request` passes `cancel_on_abandon=False` for `initialize` — the spec forbids
    cancelling it — and leaves the option unset for every other method."""

    class RecordingDispatcher:
        """Records `send_raw_request` opts and answers with canned results."""

        def __init__(self) -> None:
            self.calls: list[tuple[str, CallOptions]] = []

        async def run(
            self,
            on_request: OnRequest,
            on_notify: OnNotify,
            *,
            task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
        ) -> None:
            task_status.started()
            await anyio.sleep_forever()

        async def send_raw_request(
            self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None
        ) -> dict[str, Any]:
            self.calls.append((method, opts or {}))
            if method == "initialize":
                return InitializeResult(
                    protocol_version=LATEST_HANDSHAKE_VERSION,
                    capabilities=ServerCapabilities(),
                    server_info=Implementation(name="mock-server", version="0.1.0"),
                ).model_dump(by_alias=True, mode="json", exclude_none=True)
            return {}

        async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
            pass

    dispatcher = RecordingDispatcher()
    with anyio.fail_after(5):
        async with ClientSession(dispatcher=dispatcher) as session:
            await session.initialize()
            await session.send_ping()
    opts_by_method = dict(dispatcher.calls)
    assert opts_by_method["initialize"].get("cancel_on_abandon") is False
    assert "cancel_on_abandon" not in opts_by_method["ping"]


def test_constructor_rejects_streams_and_dispatcher_together():
    client_side, _server_side = create_direct_dispatcher_pair()
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    with pytest.raises(ValueError, match="not both"):
        ClientSession(s2c_recv, dispatcher=client_side)
    s2c_send.close()
    s2c_recv.close()


def test_constructor_requires_both_streams_without_dispatcher():
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](1)
    with pytest.raises(ValueError, match="read_stream and write_stream are required"):
        ClientSession(s2c_recv)
    with pytest.raises(ValueError, match="read_stream and write_stream are required"):
        ClientSession()
    s2c_send.close()
    s2c_recv.close()


@pytest.mark.anyio
async def test_aenter_cancelled_while_dispatcher_starts_unwinds_cleanly():
    """Cancellation while `__aenter__` waits for the dispatcher to start unwinds the half-entered
    task group cleanly, not via anyio's "exited non-innermost cancel scope" RuntimeError (SDK-defined)."""

    class NeverStartsDispatcher:
        """`run()` parks without ever signalling `task_status.started()`."""

        async def run(
            self,
            on_request: OnRequest,
            on_notify: OnNotify,
            *,
            task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
        ) -> None:
            await anyio.sleep_forever()

        async def send_raw_request(
            self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None
        ) -> dict[str, Any]:
            raise NotImplementedError

        async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
            raise NotImplementedError

    session = ClientSession(dispatcher=NeverStartsDispatcher())
    async with AsyncExitStack() as stack:
        # `start()` is parked forever, so the deadline only ends the wait — any duration is non-racy.
        with anyio.move_on_after(0.01) as scope:
            await stack.enter_async_context(session)
    assert scope.cancelled_caught
    # The failed enter must not leave the session half-entered.
    assert session._task_group is None


@pytest.mark.anyio
async def test_send_notification_after_close_is_dropped_silently():
    """Post-close `send_notification` is fire-and-forget: the notification is dropped,
    not surfaced as a raw transport error (v1 leaked `anyio.ClosedResourceError`)."""
    s2c_send, s2c_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)
    c2s_send, c2s_recv = anyio.create_memory_object_stream[SessionMessage](4)
    try:
        async with ClientSession(s2c_recv, c2s_send) as session:
            pass
        with anyio.fail_after(5):
            await session.send_notification(types.RootsListChangedNotification())
        with pytest.raises(anyio.EndOfStream):
            c2s_recv.receive_nowait()  # nothing reached the wire
    finally:
        for s in (s2c_send, s2c_recv, c2s_send, c2s_recv):
            s.close()


# --- discover() ladder ---


class _ScriptedDispatcher:
    """Records every `send_raw_request` and plays back scripted answers in order.

    A script entry that is an `Exception` is raised; a dict is returned."""

    def __init__(self, *script: dict[str, Any] | Exception) -> None:
        self.calls: list[tuple[str, Mapping[str, Any] | None]] = []
        self.notifies: list[str] = []
        self._script: list[dict[str, Any] | Exception] = list(script)

    async def run(
        self,
        on_request: OnRequest,
        on_notify: OnNotify,
        *,
        task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED,
    ) -> None:
        task_status.started()
        await anyio.sleep_forever()

    async def send_raw_request(
        self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None
    ) -> dict[str, Any]:
        self.calls.append((method, params))
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def notify(self, method: str, params: Mapping[str, Any] | None, opts: CallOptions | None = None) -> None:
        self.notifies.append(method)


def _discover_result_dict() -> dict[str, Any]:
    return types.DiscoverResult(
        supported_versions=["2026-07-28"],
        capabilities=ServerCapabilities(),
        server_info=Implementation(name="stub", version="0"),
    ).model_dump(by_alias=True, mode="json", exclude_none=True)


@pytest.mark.anyio
async def test_initialize_is_idempotent_and_returns_the_cached_result() -> None:
    """A second `initialize()` returns the first call's result by identity and sends nothing
    over the wire — the early-return guard short-circuits before the dispatcher is touched."""
    init_result = InitializeResult(
        protocol_version=LATEST_HANDSHAKE_VERSION,
        capabilities=ServerCapabilities(),
        server_info=Implementation(name="mock-server", version="0.1.0"),
    ).model_dump(by_alias=True, mode="json", exclude_none=True)
    dispatcher = _ScriptedDispatcher(init_result)
    with anyio.fail_after(5):
        async with ClientSession(dispatcher=dispatcher) as session:
            first = await session.initialize()
            second = await session.initialize()
    assert first is second
    assert [method for method, _ in dispatcher.calls] == ["initialize"]
    assert dispatcher.notifies == ["notifications/initialized"]


@pytest.mark.anyio
async def test_discover_adopts_the_returned_result_and_installs_the_modern_stamp() -> None:
    """SDK-defined: a successful `server/discover` is adopted and subsequent requests
    carry the modern `_meta` envelope (protocol version + client info + capabilities)."""
    dispatcher = _ScriptedDispatcher(_discover_result_dict(), {})
    with anyio.fail_after(5):
        async with ClientSession(dispatcher=dispatcher) as session:
            result = await session.discover()
            assert isinstance(result, types.DiscoverResult)
            assert session.protocol_version == "2026-07-28"
            await session.send_ping()
    ping_method, ping_params = dispatcher.calls[-1]
    assert ping_method == "ping"
    assert ping_params is not None
    assert ping_params["_meta"][PROTOCOL_VERSION_META_KEY] == "2026-07-28"


@pytest.mark.anyio
async def test_discover_retries_once_on_unsupported_version_then_adopts() -> None:
    """Spec SHOULD: a -32022 reply that names a mutually-supported version
    triggers exactly one retry at that version, and the retry's result is adopted."""
    dispatcher = _ScriptedDispatcher(
        MCPError(
            UNSUPPORTED_PROTOCOL_VERSION,
            "unsupported",
            data={"supported": ["2026-07-28"], "requested": "2026-07-28"},
        ),
        _discover_result_dict(),
    )
    with anyio.fail_after(5):
        async with ClientSession(dispatcher=dispatcher) as session:
            await session.discover()
    assert session.protocol_version == "2026-07-28"
    assert [m for m, _ in dispatcher.calls] == ["server/discover", "server/discover"]


@pytest.mark.anyio
async def test_discover_raises_when_retry_intersection_is_empty() -> None:
    """Spec SHOULD: a -32022 reply whose `supported` list shares nothing with the
    client's modern versions is unrecoverable — the original error is re-raised
    without a second probe."""
    dispatcher = _ScriptedDispatcher(
        MCPError(
            UNSUPPORTED_PROTOCOL_VERSION,
            "unsupported",
            data={"supported": ["1999-01-01"], "requested": "2026-07-28"},
        ),
    )
    with anyio.fail_after(5):
        async with ClientSession(dispatcher=dispatcher) as session:
            with pytest.raises(MCPError) as exc:
                await session.discover()
            assert exc.value.error.code == UNSUPPORTED_PROTOCOL_VERSION
    assert [m for m, _ in dispatcher.calls] == ["server/discover"]


@pytest.mark.anyio
@pytest.mark.parametrize("code", [METHOD_NOT_FOUND, REQUEST_TIMEOUT, INTERNAL_ERROR])
async def test_discover_reraises_non_retry_errors_without_falling_back(code: int) -> None:
    """SDK-defined: any error outside the -32022 retry rung propagates verbatim
    — `discover()` does not fall back to `initialize()` itself; that is the
    caller's policy (`Client.__aenter__`)."""
    dispatcher = _ScriptedDispatcher(MCPError(code, "nope"))
    with anyio.fail_after(5):
        async with ClientSession(dispatcher=dispatcher) as session:
            with pytest.raises(MCPError) as exc:
                await session.discover()
            assert exc.value.error.code == code
            assert session.protocol_version is None
    assert [m for m, _ in dispatcher.calls] == ["server/discover"]
    assert dispatcher.notifies == []


@pytest.mark.anyio
async def test_discover_validates_the_response_shape_before_adopting() -> None:
    """SDK-defined: the raw response is run through `DiscoverResult` validation
    before any state is installed, so a malformed reply leaves the session
    un-adopted rather than half-configured."""
    dispatcher = _ScriptedDispatcher({"supportedVersions": ["2026-07-28"]})
    session = ClientSession(dispatcher=dispatcher)
    with anyio.fail_after(5):
        async with session:
            with pytest.raises(ValidationError):
                await session.discover()
            assert session.protocol_version is None


@pytest.mark.anyio
async def test_discover_is_idempotent_and_returns_the_cached_result() -> None:
    """SDK-defined: a second `discover()` returns the already-adopted result without
    re-probing — the script holds exactly one entry, so a second wire call would
    `IndexError` on the empty script."""
    dispatcher = _ScriptedDispatcher(_discover_result_dict())
    with anyio.fail_after(5):
        async with ClientSession(dispatcher=dispatcher) as session:
            first = await session.discover()
            assert isinstance(first, types.DiscoverResult)
            assert await session.discover() is first
            assert session.discover_result is first
    assert [m for m, _ in dispatcher.calls] == ["server/discover"]


def test_era_neutral_properties_are_none_before_any_handshake() -> None:
    """SDK-defined: the era-neutral accessors all read as None on a fresh session."""
    client_d, _ = create_direct_dispatcher_pair()
    session = ClientSession(dispatcher=client_d)
    assert session.protocol_version is None
    assert session.server_info is None
    assert session.server_capabilities is None
    assert session.instructions is None
    assert session.discover_result is None
    assert session.initialize_result is None


@pytest.mark.anyio
async def test_era_neutral_properties_after_discover() -> None:
    """SDK-defined: after `discover()` the era-neutral accessors read from the
    DiscoverResult; `initialize_result` stays None."""
    raw = types.DiscoverResult(
        supported_versions=["2026-07-28"],
        capabilities=ServerCapabilities(tools=types.ToolsCapability(list_changed=True)),
        server_info=Implementation(name="discovered", version="2.0"),
        instructions="hello",
    ).model_dump(by_alias=True, mode="json", exclude_none=True)
    dispatcher = _ScriptedDispatcher(raw)
    with anyio.fail_after(5):
        async with ClientSession(dispatcher=dispatcher) as session:
            await session.discover()
    assert session.protocol_version == "2026-07-28"
    assert session.server_info == Implementation(name="discovered", version="2.0")
    assert session.server_capabilities == ServerCapabilities(tools=types.ToolsCapability(list_changed=True))
    assert session.instructions == "hello"
    assert session.initialize_result is None
    assert isinstance(session.discover_result, types.DiscoverResult)


@pytest.mark.anyio
async def test_discover_reraises_unsupported_version_with_malformed_error_data() -> None:
    """SDK-defined: a -32022 reply whose `data` is not a valid
    `UnsupportedProtocolVersionErrorData` payload is unrecoverable — the original
    error is re-raised without a retry probe."""
    dispatcher = _ScriptedDispatcher(MCPError(UNSUPPORTED_PROTOCOL_VERSION, "unsupported", data="not-an-object"))
    with anyio.fail_after(5):
        async with ClientSession(dispatcher=dispatcher) as session:
            with pytest.raises(MCPError) as exc:
                await session.discover()
            assert exc.value.error.code == UNSUPPORTED_PROTOCOL_VERSION
    assert [m for m, _ in dispatcher.calls] == ["server/discover"]


@pytest.mark.anyio
async def test_session_call_tool_returns_input_required_result_when_opted_in() -> None:
    """`ClientSession.call_tool(..., allow_input_required=True)` surfaces the
    raw `InputRequiredResult` so the caller can drive the loop manually."""

    # `on_call_tool` is still typed `-> CallToolResult` on this branch (#2967 widens it later);
    # `add_request_handler` is `HandlerResult`-typed and accepts `InputRequiredResult` cleanly.
    async def handler(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.InputRequiredResult:
        return types.InputRequiredResult(request_state="s")

    server = Server("test")
    server.add_request_handler("tools/call", types.CallToolRequestParams, handler)
    with anyio.fail_after(5):
        async with Client(server, mode="2026-07-28") as client:
            result = await client.session.call_tool("ask", allow_input_required=True)
    assert isinstance(result, types.InputRequiredResult)
    assert result.request_state == "s"


@pytest.mark.anyio
async def test_call_tool_threads_input_responses_and_request_state_into_params() -> None:
    captured: list[types.CallToolRequestParams] = []

    async def on_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        captured.append(params)
        return CallToolResult(content=[])

    async def on_list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[])

    server = Server("test", on_call_tool=on_call_tool, on_list_tools=on_list_tools)
    with anyio.fail_after(5):
        async with Client(server, mode="2026-07-28") as client:
            await client.call_tool(
                "ask",
                input_responses={"k": types.ElicitResult(action="decline")},
                request_state="s",
            )
    assert captured[0].input_responses == {"k": types.ElicitResult(action="decline")}
    assert captured[0].request_state == "s"


@pytest.mark.anyio
async def test_session_call_tool_raises_on_input_required_without_opt_in() -> None:
    """SDK-defined: `ClientSession.call_tool` is mechanics-only; an
    `InputRequiredResult` with the default `allow_input_required=False` raises
    `RuntimeError` (the auto-loop policy lives on `Client`, not here)."""

    async def handler(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.InputRequiredResult:
        return types.InputRequiredResult(request_state="s")

    server = Server("test")
    server.add_request_handler("tools/call", types.CallToolRequestParams, handler)
    with anyio.fail_after(5):
        async with Client(server, mode="2026-07-28") as client:
            with pytest.raises(RuntimeError, match="allow_input_required=True"):
                await client.session.call_tool("t")
            result = await client.session.call_tool("t", allow_input_required=True)
    assert isinstance(result, types.InputRequiredResult)


@pytest.mark.anyio
async def test_session_get_prompt_returns_input_required_result_when_opted_in() -> None:
    """`ClientSession.get_prompt` mirrors `call_tool`: opting in returns the
    raw `InputRequiredResult`; the default raises `RuntimeError`."""

    async def handler(ctx: ServerRequestContext, params: types.GetPromptRequestParams) -> types.InputRequiredResult:
        return types.InputRequiredResult(request_state="prompt-state")

    server = Server("test")
    server.add_request_handler("prompts/get", types.GetPromptRequestParams, handler)
    with anyio.fail_after(5):
        async with Client(server, mode="2026-07-28") as client:
            with pytest.raises(RuntimeError, match="allow_input_required=True"):
                await client.session.get_prompt("p")
            result = await client.session.get_prompt("p", allow_input_required=True)
    assert isinstance(result, types.InputRequiredResult)
    assert result.request_state == "prompt-state"


@pytest.mark.anyio
async def test_session_read_resource_returns_input_required_result_when_opted_in() -> None:
    """`ClientSession.read_resource` mirrors `call_tool`: opting in returns the
    raw `InputRequiredResult`; the default raises `RuntimeError`."""

    async def handler(ctx: ServerRequestContext, params: types.ReadResourceRequestParams) -> types.InputRequiredResult:
        return types.InputRequiredResult(request_state="resource-state")

    server = Server("test")
    server.add_request_handler("resources/read", types.ReadResourceRequestParams, handler)
    with anyio.fail_after(5):
        async with Client(server, mode="2026-07-28") as client:
            with pytest.raises(RuntimeError, match="allow_input_required=True"):
                await client.session.read_resource("memory://r")
            result = await client.session.read_resource("memory://r", allow_input_required=True)
    assert isinstance(result, types.InputRequiredResult)
    assert result.request_state == "resource-state"
