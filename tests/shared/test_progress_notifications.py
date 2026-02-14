from typing import Any
from unittest.mock import patch

import anyio
import pytest

from mcp import Client, types
from mcp.client.session import ClientSession
from mcp.server import Server, ServerRequestContext
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared._context import RequestContext
from mcp.shared.message import SessionMessage
from mcp.shared.progress import progress
from mcp.shared.session import RequestResponder


@pytest.mark.anyio
async def test_bidirectional_progress_notifications():
    """Test that both client and server can send progress notifications."""
    # Create memory streams for client/server
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](5)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](5)

    # Run a server session so we can send progress updates in tool
    async def run_server():
        # Create a server session
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="ProgressTestServer",
                server_version="0.1.0",
                capabilities=server.get_capabilities(NotificationOptions(), {}),
            ),
        ) as server_session:
            async for message in server_session.incoming_messages:
                try:
                    await server._handle_message(message, server_session, {})
                except Exception as e:  # pragma: no cover
                    raise e

    # Track progress updates
    server_progress_updates: list[dict[str, Any]] = []
    client_progress_updates: list[dict[str, Any]] = []
    all_server_progress_received = anyio.Event()

    # Progress tokens
    server_progress_token = "server_token_123"
    client_progress_token = "client_token_456"

    # Register progress handler
    async def handle_progress(ctx: ServerRequestContext, params: types.ProgressNotificationParams) -> None:
        server_progress_updates.append(
            {
                "token": params.progress_token,
                "progress": params.progress,
                "total": params.total,
                "message": params.message,
            }
        )
        if len(server_progress_updates) == 3:
            all_server_progress_received.set()

    # Register list tool handler
    async def handle_list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="test_tool",
                    description="A tool that sends progress notifications <o/",
                    input_schema={},
                )
            ]
        )

    # Register tool handler
    async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
        # Make sure we received a progress token
        if params.name == "test_tool":
            assert params.meta is not None
            progress_token = params.meta.get("progress_token")
            assert progress_token is not None
            assert progress_token == client_progress_token

            # Send progress notifications using ctx.session
            await ctx.session.send_progress_notification(
                progress_token=progress_token,
                progress=0.25,
                total=1.0,
                message="Server progress 25%",
            )

            await ctx.session.send_progress_notification(
                progress_token=progress_token,
                progress=0.5,
                total=1.0,
                message="Server progress 50%",
            )

            await ctx.session.send_progress_notification(
                progress_token=progress_token,
                progress=1.0,
                total=1.0,
                message="Server progress 100%",
            )

            return types.CallToolResult(content=[types.TextContent(type="text", text="Tool executed successfully")])

        raise ValueError(f"Unknown tool: {params.name}")  # pragma: no cover

    # Create a server with progress capability
    server = Server(
        name="ProgressTestServer",
        on_progress=handle_progress,
        on_list_tools=handle_list_tools,
        on_call_tool=handle_call_tool,
    )

    # Client message handler to store progress notifications
    async def handle_client_message(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):  # pragma: no cover
            raise message

        if isinstance(message, types.ServerNotification):  # pragma: no branch
            if isinstance(message, types.ProgressNotification):  # pragma: no branch
                params = message.params
                client_progress_updates.append(
                    {
                        "token": params.progress_token,
                        "progress": params.progress,
                        "total": params.total,
                        "message": params.message,
                    }
                )

    # Test using client
    async with (
        ClientSession(
            server_to_client_receive,
            client_to_server_send,
            message_handler=handle_client_message,
        ) as client_session,
        anyio.create_task_group() as tg,
    ):
        # Start the server in a background task
        tg.start_soon(run_server)

        # Initialize the client connection
        await client_session.initialize()

        # Call list_tools with progress token
        await client_session.list_tools()

        # Call test_tool with progress token
        await client_session.call_tool("test_tool", meta={"progress_token": client_progress_token})

        # Send progress notifications from client to server
        await client_session.send_progress_notification(
            progress_token=server_progress_token,
            progress=0.33,
            total=1.0,
            message="Client progress 33%",
        )

        await client_session.send_progress_notification(
            progress_token=server_progress_token,
            progress=0.66,
            total=1.0,
            message="Client progress 66%",
        )

        await client_session.send_progress_notification(
            progress_token=server_progress_token,
            progress=1.0,
            total=1.0,
            message="Client progress 100%",
        )

        # Wait for all server-side progress updates to arrive, then exit
        with anyio.fail_after(5):
            await all_server_progress_received.wait()
        tg.cancel_scope.cancel()

    # Verify client received progress updates from server
    assert len(client_progress_updates) == 3
    assert client_progress_updates[0]["token"] == client_progress_token
    assert client_progress_updates[0]["progress"] == 0.25
    assert client_progress_updates[0]["message"] == "Server progress 25%"
    assert client_progress_updates[2]["progress"] == 1.0

    # Verify server received progress updates from client
    assert len(server_progress_updates) == 3
    assert server_progress_updates[0]["token"] == server_progress_token
    assert server_progress_updates[0]["progress"] == 0.33
    assert server_progress_updates[0]["message"] == "Client progress 33%"
    assert server_progress_updates[2]["progress"] == 1.0


@pytest.mark.anyio
async def test_progress_context_manager():
    """Test client using progress context manager for sending progress notifications."""
    # Create memory streams for client/server
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](5)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](5)

    # Track progress updates
    server_progress_updates: list[dict[str, Any]] = []
    all_progress_received = anyio.Event()

    progress_token = None

    # Register progress handler
    async def handle_progress(ctx: ServerRequestContext, params: types.ProgressNotificationParams) -> None:
        server_progress_updates.append(
            {
                "token": params.progress_token,
                "progress": params.progress,
                "total": params.total,
                "message": params.message,
            }
        )
        if len(server_progress_updates) == 4:
            all_progress_received.set()

    server = Server(name="ProgressContextTestServer", on_progress=handle_progress)

    # Run server session to receive progress updates
    async def run_server():
        # Create a server session
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="ProgressContextTestServer",
                server_version="0.1.0",
                capabilities=server.get_capabilities(NotificationOptions(), {}),
            ),
        ) as server_session:
            async for message in server_session.incoming_messages:
                try:
                    await server._handle_message(message, server_session, {})
                except Exception as e:  # pragma: no cover
                    raise e

    # Client message handler
    async def handle_client_message(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):  # pragma: no cover
            raise message

    # run client session
    async with (
        ClientSession(
            server_to_client_receive,
            client_to_server_send,
            message_handler=handle_client_message,
        ) as client_session,
        anyio.create_task_group() as tg,
    ):
        tg.start_soon(run_server)

        await client_session.initialize()

        progress_token = "client_token_456"

        # Create request context
        request_context = RequestContext(
            request_id="test-request",
            session=client_session,
            meta={"progress_token": progress_token},
        )

        # Utilize progress context manager
        with progress(request_context, total=100) as p:
            await p.progress(10, message="Loading configuration...")
            await p.progress(30, message="Connecting to database...")
            await p.progress(40, message="Fetching data...")
            await p.progress(20, message="Processing results...")

        # Wait for all progress updates to arrive, then exit
        with anyio.fail_after(5):
            await all_progress_received.wait()
        tg.cancel_scope.cancel()

    # Verify progress updates were received by server
    assert len(server_progress_updates) == 4

    # first update
    assert server_progress_updates[0]["token"] == progress_token
    assert server_progress_updates[0]["progress"] == 10
    assert server_progress_updates[0]["total"] == 100
    assert server_progress_updates[0]["message"] == "Loading configuration..."

    # second update
    assert server_progress_updates[1]["token"] == progress_token
    assert server_progress_updates[1]["progress"] == 40
    assert server_progress_updates[1]["total"] == 100
    assert server_progress_updates[1]["message"] == "Connecting to database..."

    # third update
    assert server_progress_updates[2]["token"] == progress_token
    assert server_progress_updates[2]["progress"] == 80
    assert server_progress_updates[2]["total"] == 100
    assert server_progress_updates[2]["message"] == "Fetching data..."

    # final update
    assert server_progress_updates[3]["token"] == progress_token
    assert server_progress_updates[3]["progress"] == 100
    assert server_progress_updates[3]["total"] == 100
    assert server_progress_updates[3]["message"] == "Processing results..."


@pytest.mark.anyio
async def test_progress_callback_exception_logging():
    """Test that exceptions in progress callbacks are logged and \
        don't crash the session."""
    # Track logged warnings
    logged_errors: list[str] = []

    def mock_log_exception(msg: str, *args: Any, **kwargs: Any) -> None:
        logged_errors.append(msg % args if args else msg)

    # Create a progress callback that raises an exception
    async def failing_progress_callback(progress: float, total: float | None, message: str | None) -> None:
        raise ValueError("Progress callback failed!")

    # Create a server with a tool that sends progress notifications
    async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
        if params.name == "progress_tool":
            assert ctx.request_id is not None
            # Send a progress notification
            await ctx.session.send_progress_notification(
                progress_token=ctx.request_id,
                progress=50.0,
                total=100.0,
                message="Halfway done",
            )
            return types.CallToolResult(content=[types.TextContent(type="text", text="progress_result")])
        raise ValueError(f"Unknown tool: {params.name}")  # pragma: no cover

    async def handle_list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="progress_tool",
                    description="A tool that sends progress notifications",
                    input_schema={},
                )
            ]
        )

    server = Server(
        name="TestProgressServer",
        on_call_tool=handle_call_tool,
        on_list_tools=handle_list_tools,
    )

    # Test with mocked logging
    with patch("mcp.shared.session.logging.exception", side_effect=mock_log_exception):
        async with Client(server) as client:
            # Call tool with a failing progress callback
            result = await client.call_tool(
                "progress_tool",
                arguments={},
                progress_callback=failing_progress_callback,
            )

            # Verify the request completed successfully despite the callback failure
            assert len(result.content) == 1
            content = result.content[0]
            assert isinstance(content, types.TextContent)
            assert content.text == "progress_result"

            # Check that a warning was logged for the progress callback exception
            assert len(logged_errors) > 0
            assert any("Progress callback raised an exception" in warning for warning in logged_errors)
