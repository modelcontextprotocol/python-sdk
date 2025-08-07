import asyncio
from typing import Any, cast

import anyio
import pytest

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext
from mcp.shared.message import SessionMessage
from mcp.shared.progress import progress
from mcp.shared.session import (
    BaseSession,
    RequestResponder,
)


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
            global serv_sesh

            serv_sesh = server_session
            async for message in server_session.incoming_messages:
                try:
                    await server._handle_message(message, server_session, {})
                except Exception as e:
                    raise e

    # Track progress updates
    server_progress_updates = []
    client_progress_updates = []

    # Progress tokens
    server_progress_token = "server_token_123"
    client_progress_token = "client_token_456"

    # Create a server with progress capability
    server = Server(name="ProgressTestServer")

    # Register progress handler
    @server.progress_notification()
    async def handle_progress(
        progress_token: str | int,
        progress: float,
        total: float | None,
        message: str | None,
    ):
        server_progress_updates.append(
            {
                "token": progress_token,
                "progress": progress,
                "total": total,
                "message": message,
            }
        )

    # Register list tool handler
    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="test_tool",
                description="A tool that sends progress notifications <o/",
                inputSchema={},
            )
        ]

    # Register tool handler
    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict | None) -> list:
        # Make sure we received a progress token
        if name == "test_tool":
            if arguments and "_meta" in arguments:
                progressToken = arguments["_meta"]["progressToken"]

                if not progressToken:
                    raise ValueError("Empty progress token received")

                if progressToken != client_progress_token:
                    raise ValueError("Server sending back incorrect progressToken")

                # Send progress notifications
                await serv_sesh.send_progress_notification(
                    progress_token=progressToken,
                    progress=0.25,
                    total=1.0,
                    message="Server progress 25%",
                )

                await serv_sesh.send_progress_notification(
                    progress_token=progressToken,
                    progress=0.5,
                    total=1.0,
                    message="Server progress 50%",
                )

                await serv_sesh.send_progress_notification(
                    progress_token=progressToken,
                    progress=1.0,
                    total=1.0,
                    message="Server progress 100%",
                )

            else:
                raise ValueError("Progress token not sent.")

            return ["Tool executed successfully"]

        raise ValueError(f"Unknown tool: {name}")

    # Client message handler to store progress notifications
    async def handle_client_message(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):
            raise message

        if isinstance(message, types.ServerNotification):
            if isinstance(message.root, types.ProgressNotification):
                params = message.root.params
                client_progress_updates.append(
                    {
                        "token": params.progressToken,
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
        await client_session.call_tool("test_tool", {"_meta": {"progressToken": client_progress_token}})

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

        # Wait and exit
        await anyio.sleep(0.5)
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
    server_progress_updates = []

    server = Server(name="ProgressContextTestServer")

    # Register progress handler
    @server.progress_notification()
    async def handle_progress(
        progress_token: str | int,
        progress: float,
        total: float | None,
        message: str | None,
    ):
        server_progress_updates.append(
            {
                "token": progress_token,
                "progress": progress,
                "total": total,
                "message": message,
            }
        )

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
                except Exception as e:
                    raise e

    # Client message handler
    async def handle_client_message(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):
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
        meta = types.RequestParams.Meta(progressToken=progress_token)
        request_context = RequestContext(
            request_id="test-request",
            session=client_session,
            meta=meta,
            lifespan_context=None,
        )

        # cast for type checker
        typed_context = cast(
            RequestContext[
                BaseSession[Any, Any, Any, Any, Any],
                Any,
            ],
            request_context,
        )

        # Utilize progress context manager
        with progress(typed_context, total=100) as p:
            await p.progress(10, message="Loading configuration...")
            await p.progress(30, message="Connecting to database...")
            await p.progress(40, message="Fetching data...")
            await p.progress(20, message="Processing results...")

        # Wait for all messages to be processed
        await anyio.sleep(0.5)
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
async def test_initialized_notification():
    """Test that the server receives and handles InitializedNotification."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](1)

    server = Server("test")
    initialized_received = asyncio.Event()

    @server.initialized_notification()
    async def handle_initialized(notification: types.InitializedNotification):
        initialized_received.set()

    async def run_server():
        await server.run(
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options(),
        )

    async def message_handler(
        message: (RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception),
    ) -> None:
        if isinstance(message, Exception):
            raise message

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
        await initialized_received.wait()
        tg.cancel_scope.cancel()

    assert initialized_received.is_set()


@pytest.mark.anyio
async def test_roots_list_changed_notification():
    """Test that the server receives and handles RootsListChangedNotification."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](1)

    server = Server("test")
    roots_list_changed_received = asyncio.Event()

    @server.roots_list_changed_notification()
    async def handle_roots_list_changed(
        notification: types.RootsListChangedNotification,
    ):
        roots_list_changed_received.set()

    async def run_server():
        await server.run(
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options(),
        )

    async def message_handler(
        message: (RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception),
    ) -> None:
        if isinstance(message, Exception):
            raise message

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
        await client_session.send_notification(
            types.ClientNotification(
                root=types.RootsListChangedNotification(method="notifications/roots/list_changed", params=None)
            )
        )
        await roots_list_changed_received.wait()
        tg.cancel_scope.cancel()

    assert roots_list_changed_received.is_set()


@pytest.mark.anyio
async def test_initialized_notification_with_session():
    """Test that the server receives and handles InitializedNotification with a session."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](1)

    server = Server("test")
    initialized_received = asyncio.Event()
    received_session = None

    @server.initialized_notification()
    async def handle_initialized(notification: types.InitializedNotification, session: ServerSession):
        nonlocal received_session
        received_session = session
        initialized_received.set()

    async def run_server():
        await server.run(
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options(),
        )

    async def message_handler(
        message: (RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception),
    ) -> None:
        if isinstance(message, Exception):
            raise message

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
        await initialized_received.wait()
        tg.cancel_scope.cancel()

    assert initialized_received.is_set()
    assert isinstance(received_session, ServerSession)


@pytest.mark.anyio
async def test_roots_list_changed_notification_with_session():
    """Test that the server receives and handles RootsListChangedNotification with a session."""
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](1)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage | Exception](1)

    server = Server("test")
    roots_list_changed_received = asyncio.Event()
    received_session = None

    @server.roots_list_changed_notification()
    async def handle_roots_list_changed(notification: types.RootsListChangedNotification, session: ServerSession):
        nonlocal received_session
        received_session = session
        roots_list_changed_received.set()

    async def run_server():
        await server.run(
            client_to_server_receive,
            server_to_client_send,
            server.create_initialization_options(),
        )

    async def message_handler(
        message: (RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception),
    ) -> None:
        if isinstance(message, Exception):
            raise message

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
        await client_session.send_notification(
            types.ClientNotification(
                root=types.RootsListChangedNotification(method="notifications/roots/list_changed", params=None)
            )
        )
        await roots_list_changed_received.wait()
        tg.cancel_scope.cancel()

    assert roots_list_changed_received.is_set()
    assert isinstance(received_session, ServerSession)
