"""Tests for client task capabilities declaration during initialization."""

import anyio
import pytest

import mcp.types as types
from mcp import ClientCapabilities
from mcp.client.experimental.task_handlers import ExperimentalTaskHandlers
from mcp.client.session import ClientSession
from mcp.shared.context import RequestContext
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
    """Test that tasks capability is properly set when handlers are provided."""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    received_capabilities: ClientCapabilities | None = None

    # Define custom handlers to trigger capability building (never actually called)
    async def my_list_tasks_handler(
        context: RequestContext[ClientSession, None],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListTasksResult | types.ErrorData:
        raise NotImplementedError

    async def my_cancel_task_handler(
        context: RequestContext[ClientSession, None],
        params: types.CancelTaskRequestParams,
    ) -> types.CancelTaskResult | types.ErrorData:
        raise NotImplementedError

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

    # Create handlers container
    task_handlers = ExperimentalTaskHandlers(
        list_tasks=my_list_tasks_handler,
        cancel_task=my_cancel_task_handler,
    )

    async with (
        ClientSession(
            server_to_client_receive,
            client_to_server_send,
            experimental_task_handlers=task_handlers,
        ) as session,
        anyio.create_task_group() as tg,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        tg.start_soon(mock_server)
        await session.initialize()

    # Assert that tasks capability is properly set from handlers
    assert received_capabilities is not None
    assert received_capabilities.tasks is not None
    assert isinstance(received_capabilities.tasks, types.ClientTasksCapability)
    assert received_capabilities.tasks.list is not None
    assert received_capabilities.tasks.cancel is not None


@pytest.mark.anyio
async def test_client_capabilities_auto_built_from_handlers():
    """Test that tasks capability is automatically built from provided handlers."""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    received_capabilities: ClientCapabilities | None = None

    # Define custom handlers (not defaults)
    async def my_list_tasks_handler(
        context: RequestContext[ClientSession, None],
        params: types.PaginatedRequestParams | None,
    ) -> types.ListTasksResult | types.ErrorData:
        raise NotImplementedError

    async def my_cancel_task_handler(
        context: RequestContext[ClientSession, None],
        params: types.CancelTaskRequestParams,
    ) -> types.CancelTaskResult | types.ErrorData:
        raise NotImplementedError

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

    # Provide handlers via ExperimentalTaskHandlers
    task_handlers = ExperimentalTaskHandlers(
        list_tasks=my_list_tasks_handler,
        cancel_task=my_cancel_task_handler,
    )

    async with (
        ClientSession(
            server_to_client_receive,
            client_to_server_send,
            experimental_task_handlers=task_handlers,
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


@pytest.mark.anyio
async def test_client_capabilities_with_task_augmented_handlers():
    """Test that requests capability is built when augmented handlers are provided."""
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)

    received_capabilities: ClientCapabilities | None = None

    # Define task-augmented handler
    async def my_augmented_sampling_handler(
        context: RequestContext[ClientSession, None],
        params: types.CreateMessageRequestParams,
        task_metadata: types.TaskMetadata,
    ) -> types.CreateTaskResult | types.ErrorData:
        raise NotImplementedError

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

    # Provide task-augmented sampling handler
    task_handlers = ExperimentalTaskHandlers(
        augmented_sampling=my_augmented_sampling_handler,
    )

    async with (
        ClientSession(
            server_to_client_receive,
            client_to_server_send,
            experimental_task_handlers=task_handlers,
        ) as session,
        anyio.create_task_group() as tg,
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        tg.start_soon(mock_server)
        await session.initialize()

    # Assert that tasks capability includes requests.sampling
    assert received_capabilities is not None
    assert received_capabilities.tasks is not None
    assert received_capabilities.tasks.requests is not None
    assert received_capabilities.tasks.requests.sampling is not None
    assert received_capabilities.tasks.requests.elicitation is None  # Not provided
