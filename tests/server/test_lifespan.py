"""Tests for lifespan functionality in both low-level and MCPServer servers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio
import pytest
from pydantic import TypeAdapter

import mcp.types as types
from mcp.server.lowlevel.server import NotificationOptions, Server
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.context import RequestContext
from mcp.shared.message import SessionMessage
from mcp.types import (
    ClientCapabilities,
    Implementation,
    InitializeRequestParams,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    TextContent,
)


@pytest.mark.anyio
async def test_lowlevel_server_lifespan():
    """Test that lifespan works in low-level server."""

    @asynccontextmanager
    async def test_lifespan(server: ServerSession) -> AsyncIterator[dict[str, bool]]:
        """Test lifespan context that tracks startup/shutdown."""
        context = {"started": False, "shutdown": False}
        try:
            context["started"] = True
            yield context
        finally:
            context["shutdown"] = True

    async def on_call_tool(
        ctx: RequestContext[ServerSession, dict[str, bool], Any],
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        assert isinstance(ctx.lifespan_context, dict)
        assert ctx.lifespan_context["started"]
        assert not ctx.lifespan_context["shutdown"]
        return types.CallToolResult(content=[TextContent(type="text", text="true")])

    server = Server[dict[str, bool]]("test", lifespan=test_lifespan, on_call_tool=on_call_tool)

    # Create memory streams for testing
    send_stream1, receive_stream1 = anyio.create_memory_object_stream[SessionMessage](100)
    send_stream2, receive_stream2 = anyio.create_memory_object_stream[SessionMessage](100)

    # Run server in background task
    async with anyio.create_task_group() as tg, send_stream1, receive_stream1, send_stream2, receive_stream2:

        async def run_server():
            await server.run(
                receive_stream1,
                send_stream2,
                InitializationOptions(
                    server_name="test",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
                raise_exceptions=True,
            )

        tg.start_soon(run_server)

        # Initialize the server
        params = InitializeRequestParams(
            protocol_version="2024-11-05",
            capabilities=ClientCapabilities(),
            client_info=Implementation(name="test-client", version="0.1.0"),
        )
        await send_stream1.send(
            SessionMessage(
                JSONRPCRequest(
                    jsonrpc="2.0",
                    id=1,
                    method="initialize",
                    params=TypeAdapter(InitializeRequestParams).dump_python(params),
                )
            )
        )
        response = await receive_stream2.receive()
        response = response.message

        # Send initialized notification
        await send_stream1.send(SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized")))

        # Call the tool to verify lifespan context
        await send_stream1.send(
            SessionMessage(
                JSONRPCRequest(
                    jsonrpc="2.0",
                    id=2,
                    method="tools/call",
                    params={"name": "check_lifespan", "arguments": {}},
                )
            )
        )

        # Get response and verify
        response = await receive_stream2.receive()
        response = response.message
        assert isinstance(response, JSONRPCMessage)
        assert isinstance(response, JSONRPCResponse)
        assert response.result["content"][0]["text"] == "true"

        # Cancel server task
        tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_mcpserver_server_lifespan():
    """Test that lifespan works in MCPServer server."""

    @asynccontextmanager
    async def test_lifespan(server: MCPServer) -> AsyncIterator[dict[str, bool]]:
        """Test lifespan context that tracks startup/shutdown."""
        context = {"started": False, "shutdown": False}
        try:
            context["started"] = True
            yield context
        finally:
            context["shutdown"] = True

    server = MCPServer("test", lifespan=test_lifespan)

    # Create memory streams for testing
    send_stream1, receive_stream1 = anyio.create_memory_object_stream[SessionMessage](100)
    send_stream2, receive_stream2 = anyio.create_memory_object_stream[SessionMessage](100)

    # Add a tool that checks lifespan context
    @server.tool()
    def check_lifespan(ctx: Context[ServerSession, None]) -> bool:
        """Tool that checks lifespan context."""
        assert isinstance(ctx.request_context.lifespan_context, dict)
        assert ctx.request_context.lifespan_context["started"]
        assert not ctx.request_context.lifespan_context["shutdown"]
        return True

    # Run server in background task
    async with anyio.create_task_group() as tg, send_stream1, receive_stream1, send_stream2, receive_stream2:

        async def run_server():
            await server._lowlevel_server.run(
                receive_stream1,
                send_stream2,
                server._lowlevel_server.create_initialization_options(),
                raise_exceptions=True,
            )

        tg.start_soon(run_server)

        # Initialize the server
        params = InitializeRequestParams(
            protocol_version="2024-11-05",
            capabilities=ClientCapabilities(),
            client_info=Implementation(name="test-client", version="0.1.0"),
        )
        await send_stream1.send(
            SessionMessage(
                JSONRPCRequest(
                    jsonrpc="2.0",
                    id=1,
                    method="initialize",
                    params=TypeAdapter(InitializeRequestParams).dump_python(params),
                )
            )
        )
        response = await receive_stream2.receive()
        response = response.message

        # Send initialized notification
        await send_stream1.send(SessionMessage(JSONRPCNotification(jsonrpc="2.0", method="notifications/initialized")))

        # Call the tool to verify lifespan context
        await send_stream1.send(
            SessionMessage(
                JSONRPCRequest(
                    jsonrpc="2.0",
                    id=2,
                    method="tools/call",
                    params={"name": "check_lifespan", "arguments": {}},
                )
            )
        )

        # Get response and verify
        response = await receive_stream2.receive()
        response = response.message
        assert isinstance(response, JSONRPCMessage)
        assert isinstance(response, JSONRPCResponse)
        assert response.result["content"][0]["text"] == "true"

        # Cancel server task
        tg.cancel_scope.cancel()
