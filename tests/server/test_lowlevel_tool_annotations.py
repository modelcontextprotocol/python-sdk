"""Tests for tool annotations in low-level server."""

import anyio
import pytest

from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.message import SessionMessage
from mcp.shared.session import RequestResponder
from mcp.types import (
    ClientResult,
    ServerNotification,
    ServerRequest,
    Tool,
    ToolAnnotations,
)


@pytest.mark.anyio
async def test_lowlevel_server_tool_annotations():
    """Test that tool annotations work in low-level server."""
    server = Server("test")

    # Create a tool with annotations
    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="echo",
                description="Echo a message back",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"},
                    },
                    "required": ["message"],
                },
                annotations=ToolAnnotations(
                    title="Echo Tool",
                    readOnlyHint=True,
                ),
            )
        ]

    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[
        SessionMessage
    ](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[
        SessionMessage
    ](10)

    # Message handler for client
    async def message_handler(
        message: RequestResponder[ServerRequest, ClientResult]
        | ServerNotification
        | Exception,
    ) -> None:
        if isinstance(message, Exception):
            raise message

    # Server task
    async def run_server():
        async with ServerSession(
            client_to_server_receive,
            server_to_client_send,
            InitializationOptions(
                server_name="test-server",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        ) as server_session:
            async with anyio.create_task_group() as tg:

                async def handle_messages():
                    async for message in server_session.incoming_messages:
                        await server._handle_message(message, server_session, {}, False)

                tg.start_soon(handle_messages)
                await anyio.sleep_forever()

    # Run the test
    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)

        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            message_handler=message_handler,
        ) as client_session:
            # Initialize the session
            await client_session.initialize()

            # List tools
            tools_result = await client_session.list_tools()

            # Cancel the server task
            tg.cancel_scope.cancel()

    # Verify results
    assert tools_result is not None
    assert len(tools_result.tools) == 1
    assert tools_result.tools[0].name == "echo"
    assert tools_result.tools[0].annotations is not None
    assert tools_result.tools[0].annotations.title == "Echo Tool"
    assert tools_result.tools[0].annotations.readOnlyHint is True
