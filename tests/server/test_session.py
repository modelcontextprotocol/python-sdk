from typing import Any

import anyio
import pytest

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.exceptions import McpError
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
    async def message_handler(  # pragma: no cover
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
            async for message in server_session.incoming_messages:  # pragma: no branch
                if isinstance(message, Exception):  # pragma: no cover
                    raise message

                if isinstance(message, ClientNotification) and isinstance(
                    message.root, InitializedNotification
                ):  # pragma: no branch
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
    except anyio.ClosedResourceError:  # pragma: no cover
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
    async def list_prompts() -> list[Prompt]:  # pragma: no cover
        return []

    caps = server.get_capabilities(notification_options, experimental_capabilities)
    assert caps.prompts == PromptsCapability(listChanged=False)
    assert caps.resources is None
    assert caps.completions is None

    # Add a resources handler
    @server.list_resources()
    async def list_resources() -> list[Resource]:  # pragma: no cover
        return []

    caps = server.get_capabilities(notification_options, experimental_capabilities)
    assert caps.prompts == PromptsCapability(listChanged=False)
    assert caps.resources == ResourcesCapability(subscribe=False, listChanged=False)
    assert caps.completions is None

    # Add a complete handler
    @server.completion()
    async def complete(  # pragma: no cover
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
            async for message in server_session.incoming_messages:  # pragma: no branch
                if isinstance(message, Exception):  # pragma: no cover
                    raise message

                if isinstance(message, types.ClientNotification) and isinstance(
                    message.root, InitializedNotification
                ):  # pragma: no branch
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


@pytest.mark.anyio
async def test_ping_request_before_initialization():
    """Test that ping requests are allowed before initialization is complete."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](1)

    ping_response_received = False
    ping_response_id = None

    async def run_server():
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="mcp",
                server_version="0.1.0",
                capabilities=ServerCapabilities(),
            ),
        ) as server_session:
            async for message in server_session.incoming_messages:  # pragma: no branch
                if isinstance(message, Exception):  # pragma: no cover
                    raise message

                # We should receive a ping request before initialization
                if isinstance(message, RequestResponder) and isinstance(
                    message.request.root, types.PingRequest
                ):  # pragma: no branch
                    # Respond to the ping
                    with message:
                        await message.respond(types.ServerResult(types.EmptyResult()))
                    return

    async def mock_client():
        nonlocal ping_response_received, ping_response_id

        # Send ping request before any initialization
        await client_to_server_send.send(
            SessionMessage(
                types.JSONRPCMessage(
                    types.JSONRPCRequest(
                        jsonrpc="2.0",
                        id=42,
                        method="ping",
                    )
                )
            )
        )

        # Wait for the ping response
        ping_response_message = await server_to_client_receive.receive()
        assert isinstance(ping_response_message.message.root, types.JSONRPCResponse)

        ping_response_received = True
        ping_response_id = ping_response_message.message.root.id

    async with (
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
        anyio.create_task_group() as tg,
    ):
        tg.start_soon(run_server)
        tg.start_soon(mock_client)

    assert ping_response_received
    assert ping_response_id == 42


@pytest.mark.anyio
async def test_create_message_tool_result_validation():
    """Test tool_use/tool_result validation in create_message."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](1)

    async with (
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test",
                server_version="0.1.0",
                capabilities=ServerCapabilities(),
            ),
        ) as session:
            # Set up client params with sampling.tools capability for the test
            session._client_params = types.InitializeRequestParams(
                protocolVersion=types.LATEST_PROTOCOL_VERSION,
                capabilities=types.ClientCapabilities(
                    sampling=types.SamplingCapability(tools=types.SamplingToolsCapability())
                ),
                clientInfo=types.Implementation(name="test", version="1.0"),
            )

            tool = types.Tool(name="test_tool", inputSchema={"type": "object"})
            text = types.TextContent(type="text", text="hello")
            tool_use = types.ToolUseContent(type="tool_use", id="call_1", name="test_tool", input={})
            tool_result = types.ToolResultContent(type="tool_result", toolUseId="call_1", content=[])

            # Case 1: tool_result mixed with other content
            with pytest.raises(ValueError, match="only tool_result content"):
                await session.create_message(
                    messages=[
                        types.SamplingMessage(role="user", content=text),
                        types.SamplingMessage(role="assistant", content=tool_use),
                        types.SamplingMessage(role="user", content=[tool_result, text]),  # mixed!
                    ],
                    max_tokens=100,
                    tools=[tool],
                )

            # Case 2: tool_result without previous message
            with pytest.raises(ValueError, match="requires a previous message"):
                await session.create_message(
                    messages=[types.SamplingMessage(role="user", content=tool_result)],
                    max_tokens=100,
                    tools=[tool],
                )

            # Case 3: tool_result without previous tool_use
            with pytest.raises(ValueError, match="do not match any tool_use"):
                await session.create_message(
                    messages=[
                        types.SamplingMessage(role="user", content=text),
                        types.SamplingMessage(role="user", content=tool_result),
                    ],
                    max_tokens=100,
                    tools=[tool],
                )

            # Case 4: mismatched tool IDs
            with pytest.raises(ValueError, match="ids of tool_result blocks and tool_use blocks"):
                await session.create_message(
                    messages=[
                        types.SamplingMessage(role="user", content=text),
                        types.SamplingMessage(role="assistant", content=tool_use),
                        types.SamplingMessage(
                            role="user",
                            content=types.ToolResultContent(type="tool_result", toolUseId="wrong_id", content=[]),
                        ),
                    ],
                    max_tokens=100,
                    tools=[tool],
                )

            # Case 5: text-only message with tools (no tool_results) - passes validation
            # Covers has_tool_results=False branch.
            # We use move_on_after because validation happens synchronously before
            # send_request, which would block indefinitely waiting for a response.
            # The timeout lets validation pass, then cancels the blocked send.
            with anyio.move_on_after(0.01):
                await session.create_message(
                    messages=[types.SamplingMessage(role="user", content=text)],
                    max_tokens=100,
                    tools=[tool],
                )

            # Case 6: valid matching tool_result/tool_use IDs - passes validation
            # Covers tool_use_ids == tool_result_ids branch.
            # (see Case 5 comment for move_on_after explanation)
            with anyio.move_on_after(0.01):
                await session.create_message(
                    messages=[
                        types.SamplingMessage(role="user", content=text),
                        types.SamplingMessage(role="assistant", content=tool_use),
                        types.SamplingMessage(role="user", content=tool_result),
                    ],
                    max_tokens=100,
                    tools=[tool],
                )

            # Case 7: validation runs even without `tools` parameter
            # (tool loop continuation may omit tools while containing tool_result)
            with pytest.raises(ValueError, match="do not match any tool_use"):
                await session.create_message(
                    messages=[
                        types.SamplingMessage(role="user", content=text),
                        types.SamplingMessage(role="user", content=tool_result),
                    ],
                    max_tokens=100,
                    # Note: no tools parameter
                )

            # Case 8: empty messages list - skips validation entirely
            # Covers the `if messages:` branch (line 280->302)
            with anyio.move_on_after(0.01):
                await session.create_message(
                    messages=[],
                    max_tokens=100,
                )


@pytest.mark.anyio
async def test_create_message_without_tools_capability():
    """Test that create_message raises McpError when tools are provided without capability."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](1)

    async with (
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
    ):
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test",
                server_version="0.1.0",
                capabilities=ServerCapabilities(),
            ),
        ) as session:
            # Set up client params WITHOUT sampling.tools capability
            session._client_params = types.InitializeRequestParams(
                protocolVersion=types.LATEST_PROTOCOL_VERSION,
                capabilities=types.ClientCapabilities(sampling=types.SamplingCapability()),
                clientInfo=types.Implementation(name="test", version="1.0"),
            )

            tool = types.Tool(name="test_tool", inputSchema={"type": "object"})
            text = types.TextContent(type="text", text="hello")

            # Should raise McpError when tools are provided but client lacks capability
            with pytest.raises(McpError) as exc_info:
                await session.create_message(
                    messages=[types.SamplingMessage(role="user", content=text)],
                    max_tokens=100,
                    tools=[tool],
                )
            assert "does not support sampling tools capability" in exc_info.value.error.message

            # Should also raise McpError when tool_choice is provided
            with pytest.raises(McpError) as exc_info:
                await session.create_message(
                    messages=[types.SamplingMessage(role="user", content=text)],
                    max_tokens=100,
                    tool_choice=types.ToolChoice(mode="auto"),
                )
            assert "does not support sampling tools capability" in exc_info.value.error.message


@pytest.mark.anyio
async def test_other_requests_blocked_before_initialization():
    """Test that non-ping requests are still blocked before initialization."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](1)

    error_response_received = False
    error_code = None

    async def run_server():
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="mcp",
                server_version="0.1.0",
                capabilities=ServerCapabilities(),
            ),
        ):
            # Server should handle the request and send an error response
            # No need to process incoming_messages since the error is handled automatically
            await anyio.sleep(0.1)  # Give time for the request to be processed

    async def mock_client():
        nonlocal error_response_received, error_code

        # Try to send a non-ping request before initialization
        await client_to_server_send.send(
            SessionMessage(
                types.JSONRPCMessage(
                    types.JSONRPCRequest(
                        jsonrpc="2.0",
                        id=1,
                        method="prompts/list",
                    )
                )
            )
        )

        # Wait for the error response
        error_message = await server_to_client_receive.receive()
        if isinstance(error_message.message.root, types.JSONRPCError):  # pragma: no branch
            error_response_received = True
            error_code = error_message.message.root.error.code

    async with (
        client_to_server_send,
        client_to_server_receive,
        server_to_client_send,
        server_to_client_receive,
        anyio.create_task_group() as tg,
    ):
        tg.start_soon(run_server)
        tg.start_soon(mock_client)

    assert error_response_received
    assert error_code == types.INVALID_PARAMS
