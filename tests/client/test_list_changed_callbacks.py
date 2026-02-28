"""Tests for tools/resources/prompts list_changed notification callbacks."""

import pytest

from mcp import Client, types
from mcp.server.mcpserver import MCPServer
from mcp.shared.session import RequestResponder


class ListChangedCollector:
    """Collects list_changed notification invocations."""

    def __init__(self):
        self.tool_changed_count = 0
        self.resource_changed_count = 0
        self.prompt_changed_count = 0

    async def on_tool_list_changed(self) -> None:
        self.tool_changed_count += 1

    async def on_resource_list_changed(self) -> None:
        self.resource_changed_count += 1

    async def on_prompt_list_changed(self) -> None:
        self.prompt_changed_count += 1


@pytest.mark.anyio
async def test_tool_list_changed_callback():
    """Client receives tools/list_changed notification and invokes callback."""
    server = MCPServer("test")
    collector = ListChangedCollector()

    @server.tool("trigger_tool_change")
    async def trigger_tool_change() -> str:
        ctx = server.get_context()
        await ctx.session.send_notification(types.ToolListChangedNotification())
        return "ok"

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):
            raise message

    async with Client(
        server,
        tool_list_changed_callback=collector.on_tool_list_changed,
        message_handler=message_handler,
    ) as client:
        result = await client.call_tool("trigger_tool_change", {})
        assert result.is_error is False
        assert collector.tool_changed_count == 1


@pytest.mark.anyio
async def test_resource_list_changed_callback():
    """Client receives resources/list_changed notification and invokes callback."""
    server = MCPServer("test")
    collector = ListChangedCollector()

    @server.tool("trigger_resource_change")
    async def trigger_resource_change() -> str:
        ctx = server.get_context()
        await ctx.session.send_notification(types.ResourceListChangedNotification())
        return "ok"

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):
            raise message

    async with Client(
        server,
        resource_list_changed_callback=collector.on_resource_list_changed,
        message_handler=message_handler,
    ) as client:
        result = await client.call_tool("trigger_resource_change", {})
        assert result.is_error is False
        assert collector.resource_changed_count == 1


@pytest.mark.anyio
async def test_prompt_list_changed_callback():
    """Client receives prompts/list_changed notification and invokes callback."""
    server = MCPServer("test")
    collector = ListChangedCollector()

    @server.tool("trigger_prompt_change")
    async def trigger_prompt_change() -> str:
        ctx = server.get_context()
        await ctx.session.send_notification(types.PromptListChangedNotification())
        return "ok"

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):
            raise message

    async with Client(
        server,
        prompt_list_changed_callback=collector.on_prompt_list_changed,
        message_handler=message_handler,
    ) as client:
        result = await client.call_tool("trigger_prompt_change", {})
        assert result.is_error is False
        assert collector.prompt_changed_count == 1


@pytest.mark.anyio
async def test_list_changed_without_callback_does_not_crash():
    """list_changed notifications are silently ignored when no callback is set."""
    server = MCPServer("test")

    @server.tool("trigger_all_changes")
    async def trigger_all_changes() -> str:
        ctx = server.get_context()
        await ctx.session.send_notification(types.ToolListChangedNotification())
        await ctx.session.send_notification(types.ResourceListChangedNotification())
        await ctx.session.send_notification(types.PromptListChangedNotification())
        return "ok"

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):
            raise message

    async with Client(
        server,
        message_handler=message_handler,
    ) as client:
        result = await client.call_tool("trigger_all_changes", {})
        assert result.is_error is False


@pytest.mark.anyio
async def test_multiple_list_changed_notifications():
    """Multiple list_changed notifications each invoke the callback."""
    server = MCPServer("test")
    collector = ListChangedCollector()

    @server.tool("trigger_double")
    async def trigger_double() -> str:
        ctx = server.get_context()
        await ctx.session.send_notification(types.ToolListChangedNotification())
        await ctx.session.send_notification(types.ToolListChangedNotification())
        return "ok"

    async def message_handler(
        message: RequestResponder[types.ServerRequest, types.ClientResult] | types.ServerNotification | Exception,
    ) -> None:
        if isinstance(message, Exception):
            raise message

    async with Client(
        server,
        tool_list_changed_callback=collector.on_tool_list_changed,
        message_handler=message_handler,
    ) as client:
        result = await client.call_tool("trigger_double", {})
        assert result.is_error is False
        assert collector.tool_changed_count == 2
