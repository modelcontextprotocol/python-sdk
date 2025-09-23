from typing import Any

import anyio
import pytest

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import (
    ClientNotification,
    Completion,
    CompletionArgument,
    CompletionContext,
    CompletionsCapability,
    InitializedNotification,
    Prompt,
    PromptReference,
    PromptsCapability,
    Resource,
    ResourcesCapability,
    ResourceTemplateReference,
    ServerCapabilities,
)


@pytest.mark.anyio
async def test_server_session_initialize():
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](1)

    # Create a message handler to catch exceptions
    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):
            raise message

    received_initialized = False

    async def run_server():
        nonlocal received_initialized

        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="mcp",
                server_version="0.1.0",
                capabilities=ServerCapabilities(),
            ),
        ) as server_session:
            async for message in server_session.incoming_messages:
                if isinstance(message, Exception):
                    raise message

                if isinstance(message, ClientNotification) and isinstance(message.root, InitializedNotification):
                    received_initialized = True
                    return

    try:
        async with (
            ClientSession(
                server_to_client_receive,
                client_to_server_send,
                message_handler=message_handler,
            ) as client_session,
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(run_server)

            await client_session.initialize()
    except anyio.ClosedResourceError:
        pass

    assert received_initialized


@pytest.mark.anyio
async def test_server_capabilities():
    server = Server("test")
    notification_options = NotificationOptions()
    experimental_capabilities: dict[str, Any] = {}

    # Initially no capabilities
    caps = server.get_capabilities(notification_options, experimental_capabilities)
    assert caps.prompts is None
    assert caps.resources is None
    assert caps.completions is None

    # Add a prompts handler
    @server.list_prompts()
    async def list_prompts() -> list[Prompt]:
        return []

    caps = server.get_capabilities(notification_options, experimental_capabilities)
    assert caps.prompts == PromptsCapability(listChanged=False)
    assert caps.resources is None
    assert caps.completions is None

    # Add a resources handler
    @server.list_resources()
    async def list_resources() -> list[Resource]:
        return []

    caps = server.get_capabilities(notification_options, experimental_capabilities)
    assert caps.prompts == PromptsCapability(listChanged=False)
    assert caps.resources == ResourcesCapability(subscribe=False, listChanged=False)
    assert caps.completions is None

    # Add a complete handler
    @server.completion()
    async def complete(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion | None:
        return Completion(
            values=["completion1", "completion2"],
        )

    caps = server.get_capabilities(notification_options, experimental_capabilities)
    assert caps.prompts == PromptsCapability(listChanged=False)
    assert caps.resources == ResourcesCapability(subscribe=False, listChanged=False)
    assert caps.completions == CompletionsCapability()


@pytest.mark.anyio
async def test_server_session_initialize_with_older_protocol_version():
    """Test that server accepts and responds with older protocol (2024-11-05)."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](1)

    received_initialized = False
    received_protocol_version = None

    async def run_server():
        nonlocal received_initialized

        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="mcp",
                server_version="0.1.0",
                capabilities=ServerCapabilities(),
            ),
        ) as server_session:
            async for message in server_session.incoming_messages:
                if isinstance(message, Exception):
                    raise message

                if isinstance(message, types.ClientNotification) and isinstance(message.root, InitializedNotification):
                    received_initialized = True
                    return

    async def mock_client():
        nonlocal received_protocol_version

        # Send initialization request with older protocol version (2024-11-05)
        await client_to_server_send.send(
            SessionMessage(
                types.JSONRPCMessage(
                    types.JSONRPCRequest(
                        jsonrpc="2.0",
                        id=1,
                        method="initialize",
                        params=types.InitializeRequestParams(
                            protocolVersion="2024-11-05",
                            capabilities=types.ClientCapabilities(),
                            clientInfo=types.Implementation(name="test-client", version="1.0.0"),
                        ).model_dump(by_alias=True, mode="json", exclude_none=True),
                    )
                )
            )
        )

        # Wait for the initialize response
        init_response_message = await server_to_client_receive.receive()
        assert isinstance(init_response_message.message.root, types.JSONRPCResponse)
        result_data = init_response_message.message.root.result
        init_result = types.InitializeResult.model_validate(result_data)

        # Check that the server responded with the requested protocol version
        received_protocol_version = init_result.protocolVersion
        assert received_protocol_version == "2024-11-05"

        # Send initialized notification
        await client_to_server_send.send(
            SessionMessage(
                types.JSONRPCMessage(
                    types.JSONRPCNotification(
                        jsonrpc="2.0",
                        method="notifications/initialized",
                    )
                )
            )
        )

    async with (
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
        anyio.create_task_group() as tg,
    ):
        tg.start_soon(run_server)
        tg.start_soon(mock_client)

    assert received_initialized
    assert received_protocol_version == "2024-11-05"
