"""Tests for client task capabilities declaration during initialization."""

import anyio
import pytest

import mcp.types as types
from mcp import ClientCapabilities
from mcp.client.session import ClientSession
from mcp.shared.message import SessionMessage
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    ClientRequest,
    Implementation,
    InitializeRequest,
    InitializeResult,
    JSONRPCMessage,
    JSONRPCRequest,
    JSONRPCResponse,
    ServerCapabilities,
    ServerResult,
)


@pytest.mark.anyio
async def test_client_capabilities_without_tasks():
    """Test that tasks capability is None when not provided."""
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

    # Assert that tasks capability is None when not provided
    assert received_capabilities is not None
    assert received_capabilities.tasks is None


@pytest.mark.anyio
async def test_client_capabilities_with_tasks():
    """Test that tasks capability is properly set when provided."""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    received_capabilities: ClientCapabilities | None = None

    tasks_capability = types.ClientTasksCapability(
        list=types.TasksListCapability(),
        cancel=types.TasksCancelCapability(),
    )

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
            await client_to_server_receive.receive()

    async with (
        ClientSession(
            server_to_client_receive,
            client_to_server_send,
            tasks_capability=tasks_capability,
        ) as session,
        anyio.create_task_group() as tg,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        tg.start_soon(mock_server)
        await session.initialize()

    # Assert that tasks capability is properly set
    assert received_capabilities is not None
    assert received_capabilities.tasks is not None
    assert isinstance(received_capabilities.tasks, types.ClientTasksCapability)
    assert received_capabilities.tasks.list is not None
    assert received_capabilities.tasks.cancel is not None


@pytest.mark.anyio
async def test_client_capabilities_with_minimal_tasks():
    """Test that minimal tasks capability (empty object) is properly set."""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    received_capabilities = None

    # Minimal tasks capability - just declare "I understand tasks"
    tasks_capability = types.ClientTasksCapability()

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
            await client_to_server_receive.receive()

    async with (
        ClientSession(
            server_to_client_receive,
            client_to_server_send,
            tasks_capability=tasks_capability,
        ) as session,
        anyio.create_task_group() as tg,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        tg.start_soon(mock_server)
        await session.initialize()

    # Assert that minimal tasks capability is set (even with no sub-capabilities)
    assert received_capabilities is not None
    assert received_capabilities.tasks is not None
    assert isinstance(received_capabilities.tasks, types.ClientTasksCapability)
    # Sub-capabilities should be None
    assert received_capabilities.tasks.list is None
    assert received_capabilities.tasks.cancel is None


@pytest.mark.anyio
async def test_client_capabilities_auto_built_from_handlers():
    """Test that tasks capability is automatically built from provided handlers."""
    from mcp.shared.context import RequestContext

    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    received_capabilities: ClientCapabilities | None = None

    # Define custom handlers (not defaults)
    async def my_list_tasks_handler(
        context: RequestContext[ClientSession, None],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListTasksResult | types.ErrorData:
        return types.ListTasksResult(tasks=[])

    async def my_cancel_task_handler(
        context: RequestContext[ClientSession, None],
        params: types.CancelTaskRequestParams,
    ) -> types.CancelTaskResult | types.ErrorData:
        return types.ErrorData(code=types.INVALID_REQUEST, message="Not found")

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
            await client_to_server_receive.receive()

    # No tasks_capability provided - should be auto-built from handlers
    async with (
        ClientSession(
            server_to_client_receive,
            client_to_server_send,
            list_tasks_handler=my_list_tasks_handler,
            cancel_task_handler=my_cancel_task_handler,
        ) as session,
        anyio.create_task_group() as tg,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        tg.start_soon(mock_server)
        await session.initialize()

    # Assert that tasks capability was auto-built from handlers
    assert received_capabilities is not None
    assert received_capabilities.tasks is not None
    assert received_capabilities.tasks.list is not None
    assert received_capabilities.tasks.cancel is not None
    # requests should be None since we didn't provide task-augmented handlers
    assert received_capabilities.tasks.requests is None
