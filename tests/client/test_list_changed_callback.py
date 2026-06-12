"""Tests for tools/resources/prompts list_changed notification callbacks."""

import anyio
import pytest

from mcp import Client, types
from mcp.server.mcpserver import Context, MCPServer
from mcp.shared.session import RequestResponder
from mcp.types import TextContent

pytestmark = pytest.mark.anyio


async def test_tools_list_changed_callback():
    """Verify that the client invokes the tools_list_changed_callback when
    the server sends a notifications/tools/list_changed notification."""
    server = MCPServer("test")
    received = anyio.Event()

    async def on_tools_list_changed() -> None:
        received.set()

    @server.tool("trigger_tool_change")
    async def trigger_tool_change(ctx: Context) -> str:
        await ctx.session.send_tool_list_changed()
        return "triggered"

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):  # pragma: no cover
            raise message

    async with Client(
        server,
        tools_list_changed_callback=on_tools_list_changed,
        message_handler=message_handler,
    ) as client:
        result = await client.call_tool("trigger_tool_change", {})
        assert result.is_error is False
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "triggered"

        with anyio.fail_after(5):
            await received.wait()


async def test_resources_list_changed_callback():
    """Verify that the client invokes the resources_list_changed_callback when
    the server sends a notifications/resources/list_changed notification."""
    server = MCPServer("test")
    received = anyio.Event()

    async def on_resources_list_changed() -> None:
        received.set()

    @server.tool("trigger_resource_change")
    async def trigger_resource_change(ctx: Context) -> str:
        await ctx.session.send_resource_list_changed()
        return "triggered"

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):  # pragma: no cover
            raise message

    async with Client(
        server,
        resources_list_changed_callback=on_resources_list_changed,
        message_handler=message_handler,
    ) as client:
        result = await client.call_tool("trigger_resource_change", {})
        assert result.is_error is False

        with anyio.fail_after(5):
            await received.wait()


async def test_prompts_list_changed_callback():
    """Verify that the client invokes the prompts_list_changed_callback when
    the server sends a notifications/prompts/list_changed notification."""
    server = MCPServer("test")
    received = anyio.Event()

    async def on_prompts_list_changed() -> None:
        received.set()

    @server.tool("trigger_prompt_change")
    async def trigger_prompt_change(ctx: Context) -> str:
        await ctx.session.send_prompt_list_changed()
        return "triggered"

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):  # pragma: no cover
            raise message

    async with Client(
        server,
        prompts_list_changed_callback=on_prompts_list_changed,
        message_handler=message_handler,
    ) as client:
        result = await client.call_tool("trigger_prompt_change", {})
        assert result.is_error is False

        with anyio.fail_after(5):
            await received.wait()


async def test_list_changed_callbacks_not_called_without_notification():
    """Verify that list_changed callbacks are NOT invoked when
    no list_changed notification is sent."""
    server = MCPServer("test")
    called = False

    async def should_not_be_called() -> None:
        nonlocal called
        called = True  # pragma: no cover

    @server.tool("normal_tool")
    async def normal_tool() -> str:
        return "ok"

    async with Client(
        server,
        tools_list_changed_callback=should_not_be_called,
        resources_list_changed_callback=should_not_be_called,
        prompts_list_changed_callback=should_not_be_called,
    ) as client:
        result = await client.call_tool("normal_tool", {})
        assert result.is_error is False

    assert not called
