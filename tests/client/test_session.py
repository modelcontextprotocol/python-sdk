from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio
import anyio.streams.memory
import pytest

from mcp import types
from mcp.client.session import DEFAULT_CLIENT_INFO, ClientSession
from mcp.shared._context import RequestContext
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
from mcp.types import (
    INVALID_PARAMS,
    LATEST_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
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
            protocol_version=LATEST_PROTOCOL_VERSION,
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
        assert result.protocol_version == LATEST_PROTOCOL_VERSION


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
    """A server request whose method is not in the ServerRequest union gets -32601
    (METHOD_NOT_FOUND) on the wire, not a validation failure (-32602)."""
    async with raw_client_session() as (_session, to_client, from_client):
        await to_client.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=7, method="x/unknown")))
        out = await from_client.receive()
    assert isinstance(out.message, JSONRPCError)
    assert out.message.id == 7
    assert out.message.error == types.ErrorData(code=METHOD_NOT_FOUND, message="Method not found", data="x/unknown")


@pytest.mark.anyio
async def test_receive_loop_drops_unknown_notification_method_without_response():
    """An unknown notification method is dropped silently: JSON-RPC forbids
    responses to notifications, and the receive loop keeps serving."""
    async with raw_client_session() as (_session, to_client, from_client):
        await to_client.send(SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="x/unknown")))
        # The next wire output must be the answer to this follow-up ping,
        # proving the notification produced no response and the loop survived.
        await to_client.send(SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")))
        out = await from_client.receive()
    assert isinstance(out.message, JSONRPCResponse)
    assert out.message.id == 1


@pytest.mark.anyio
async def test_raising_sampling_callback_answers_with_code_zero():
    """A raising request callback is answered through the dispatcher's exception boundary."""

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
    """A notification that fails ServerNotification validation is logged and dropped."""
    seen: list[object] = []
    delivered = anyio.Event()

    async def handler(msg: object) -> None:
        seen.append(msg)
        delivered.set()

    async with raw_client_session(message_handler=handler) as (_session, to_client, _):
        await to_client.send(SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="not/a/spec/notification")))
        # Follow with a valid notification so we know the loop is still alive.
        await to_client.send(
            SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/tools/list_changed"))
        )
        await delivered.wait()
    assert isinstance(seen[0], types.ToolListChangedNotification)
    assert "Failed to validate notification" in caplog.text


@pytest.mark.anyio
async def test_receive_loop_forwards_transport_exception_to_message_handler():
    seen: list[object] = []
    delivered = anyio.Event()

    async def handler(msg: object) -> None:
        seen.append(msg)
        delivered.set()

    async with raw_client_session(message_handler=handler) as (_session, to_client, _):
        exc = ValueError("bad bytes")
        await to_client.send(exc)
        await delivered.wait()
    assert seen == [exc]


@pytest.mark.anyio
async def test_receive_loop_consumes_server_cancelled_without_reaching_message_handler():
    """A server-sent notifications/cancelled is swallowed, matching the pre-swap contract.

    The server dispatcher now emits this on sampling/elicitation timeout, but
    ClientSession has no in-flight tracking to act on it, so surfacing it would
    only break user handlers that exhaustively match ServerNotification.
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
async def test_progress_callback_exception_is_swallowed(caplog: pytest.LogCaptureFixture):
    delivered = anyio.Event()

    async def boom(progress: float, total: float | None, message: str | None) -> None:
        raise RuntimeError("progress boom")

    async def handler(msg: object) -> None:
        if isinstance(msg, types.ProgressNotification):
            delivered.set()

    async with raw_client_session(message_handler=handler) as (session, to_client, from_client):
        async with anyio.create_task_group() as tg:

            async def call() -> None:
                await session.send_request(types.PingRequest(), types.EmptyResult, progress_callback=boom)

            tg.start_soon(call)
            request = await from_client.receive()
            assert isinstance(request.message, JSONRPCRequest)
            # The request id doubles as the progress token.
            params = {"progressToken": request.message.id, "progress": 0.5}
            await to_client.send(
                SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/progress", params=params))
            )
            # The progress notification also reaches the message handler; the
            # raising callback was swallowed and logged.
            await delivered.wait()
            await to_client.send(SessionMessage(JSONRPCResponse(jsonrpc="2.0", id=request.message.id, result={})))
    assert "progress callback raised" in caplog.text


@pytest.mark.anyio
async def test_from_dispatcher_runs_over_direct_dispatch():
    """A session built with from_dispatcher works without a stream pair (in-process embedding)."""
    from mcp.shared.direct_dispatcher import create_direct_dispatcher_pair
    from mcp.shared.dispatcher import DispatchContext
    from mcp.shared.transport_context import TransportContext

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

    session = ClientSession.from_dispatcher(client_side)
    results: list[types.EmptyResult] = []
    async with anyio.create_task_group() as tg:
        await tg.start(server_side.run, server_on_request, server_on_notify)
        async with session:
            results.append(await session.send_ping(meta=None))
            # related_request_id routing is JSON-RPC plumbing; on other
            # dispatchers the notification is sent without it.
            await session.send_notification(types.RootsListChangedNotification(), related_request_id=7)
        server_side.close()
    assert results == [types.EmptyResult()]
    assert notified == ["notifications/roots/list_changed"]
