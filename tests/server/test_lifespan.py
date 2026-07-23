"""Tests for lifespan functionality in both low-level and MCPServer servers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio
import pytest
from mcp_types import (
    CallToolRequestParams,
    CallToolResult,
    ClientCapabilities,
    Implementation,
    InitializeRequestParams,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ListToolsResult,
    TextContent,
)
from pydantic import TypeAdapter

from mcp.server import ServerRequestContext
from mcp.server.lowlevel.server import NotificationOptions, Server
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.models import InitializationOptions
from mcp.shared.message import SessionMessage


@pytest.mark.anyio
async def test_lowlevel_server_lifespan():
    """Test that lifespan works in low-level server."""

    @asynccontextmanager
    async def test_lifespan(server: Server) -> AsyncIterator[dict[str, bool]]:
        """Test lifespan context that tracks startup/shutdown."""
        context = {"started": False, "shutdown": False}
        try:
            context["started"] = True
            yield context
        finally:
            context["shutdown"] = True

    # Create a tool that accesses lifespan context
    async def check_lifespan(
        ctx: ServerRequestContext[dict[str, bool]], params: CallToolRequestParams
    ) -> CallToolResult:
        assert isinstance(ctx.lifespan_context, dict)
        assert ctx.lifespan_context["started"]
        assert not ctx.lifespan_context["shutdown"]
        return CallToolResult(content=[TextContent(type="text", text="true")])

    server = Server[dict[str, bool]]("test", lifespan=test_lifespan, on_call_tool=check_lifespan)

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
    def check_lifespan(ctx: Context) -> bool:
        """Tool that checks lifespan context."""
        assert isinstance(ctx.request_context.lifespan_context, dict)
        assert ctx.request_context.lifespan_context["started"]
        assert not ctx.request_context.lifespan_context["shutdown"]
        return True

    # Run server in background task
    async with anyio.create_task_group() as tg, send_stream1, receive_stream1, send_stream2, receive_stream2:

        async def run_server():
            # `lowlevel_server` is how an MCPServer reaches the stream drivers.
            await server.lowlevel_server.run(receive_stream1, send_stream2, raise_exceptions=True)

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
async def test_server_lifespan_is_the_bound_way_to_enter_the_constructor_lifespan():
    """`server.lifespan()` enters the constructor's `lifespan=` and yields its state."""
    events: list[str] = []

    @asynccontextmanager
    async def tracked(server: Server[dict[str, str]]) -> AsyncIterator[dict[str, str]]:
        events.append(f"enter:{server.name}")
        try:
            yield {"db": "connected"}
        finally:
            events.append("exit")

    server: Server[dict[str, str]] = Server("bound", lifespan=tracked)

    async with server.lifespan() as state:
        assert state == {"db": "connected"}
        assert events == ["enter:bound"]

    assert events == ["enter:bound", "exit"]


@pytest.mark.anyio
async def test_server_run_without_initialization_options_derives_them_from_the_server():
    """`server.run(read, write)` is complete: the handshake result carries the derived options."""

    async def list_tools(ctx: ServerRequestContext[dict[str, bool]], params: Any) -> ListToolsResult:
        raise NotImplementedError

    server = Server[dict[str, bool]]("derived-options", version="9.9.9", on_list_tools=list_tools)

    send_stream1, receive_stream1 = anyio.create_memory_object_stream[SessionMessage](100)
    send_stream2, receive_stream2 = anyio.create_memory_object_stream[SessionMessage](100)

    async with anyio.create_task_group() as tg, send_stream1, receive_stream1, send_stream2, receive_stream2:
        tg.start_soon(server.run, receive_stream1, send_stream2)

        params = InitializeRequestParams(
            protocol_version="2024-11-05",
            capabilities=ClientCapabilities(),
            client_info=Implementation(name="test-client", version="0.1.0"),
        )
        with anyio.fail_after(5):
            await send_stream1.send(
                SessionMessage(
                    JSONRPCRequest(
                        jsonrpc="2.0",
                        id=1,
                        method="initialize",
                        params=params.model_dump(by_alias=True, exclude_none=True),
                    )
                )
            )
            handshake = (await receive_stream2.receive()).message

        assert isinstance(handshake, JSONRPCResponse)
        assert handshake.result["serverInfo"] == {"name": "derived-options", "version": "9.9.9"}
        # The derived options describe this server: it registered a tools handler.
        assert "tools" in handshake.result["capabilities"]

        tg.cancel_scope.cancel()
