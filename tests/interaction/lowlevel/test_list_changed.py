"""List-changed notifications from the low-level Server, driven through the public Client API.

``send_*_list_changed`` does not take a ``related_request_id``, so over streamable HTTP the
notification routes to the standalone GET stream and is not guaranteed to arrive before the tool
result on its POST stream. Tests therefore wait on an event the collector sets, the same pattern
as ``transports/test_streamable_http.py::test_unrelated_server_messages_arrive_on_the_standalone_stream``.
The collector still records every message it receives, so the length assertion also proves nothing
else was delivered.

The servers register the parent capability (resources/prompts) so that part of the spec's
precondition holds, but the ``listChanged`` sub-capability stays ``False``: ``NotificationOptions``
is not threaded through any of the suite's connection paths. The tests therefore rely on the
recorded ``lifecycle:capability:server-not-advertised`` divergence and will need updating
alongside the fix that introduces capability gating.
"""

from typing import Any

import anyio
import pytest

from mcp import types
from mcp.server import Server
from mcp.types import (
    PromptListChangedNotification,
    ResourceListChangedNotification,
    ServerNotification,
    TextContent,
    ToolListChangedNotification,
)
from tests.interaction._connect import Connect
from tests.interaction._helpers import IncomingMessage
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("tools:list-changed")
async def test_tool_list_changed_notification(connect: Connect) -> None:
    """A tools/list_changed notification sent during a tool call reaches the client's message handler."""
    received: list[IncomingMessage] = []
    seen = anyio.Event()

    async def collect(message: IncomingMessage) -> None:
        received.append(message)
        seen.set()

    server = Server("registry")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name="install", inputSchema={"type": "object"})]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        assert name == "install"
        await server.request_context.session.send_tool_list_changed()
        return [TextContent(type="text", text="installed")]

    async with connect(server, message_handler=collect) as client:
        await client.call_tool("install", {})
        with anyio.fail_after(5):
            await seen.wait()

    assert len(received) == 1
    assert isinstance(received[0], ServerNotification)
    assert isinstance(received[0].root, ToolListChangedNotification)


@requirement("resources:list-changed")
async def test_resource_list_changed_notification(connect: Connect) -> None:
    """A resources/list_changed notification sent during a tool call reaches the client's message handler."""
    received: list[IncomingMessage] = []
    seen = anyio.Event()

    async def collect(message: IncomingMessage) -> None:
        received.append(message)
        seen.set()

    server = Server("registry")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name="mount", inputSchema={"type": "object"})]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        assert name == "mount"
        await server.request_context.session.send_resource_list_changed()
        return [TextContent(type="text", text="mounted")]

    @server.list_resources()
    async def list_resources() -> list[types.Resource]:
        """Registered so the resources capability is advertised; the client never lists resources."""
        raise NotImplementedError

    async with connect(server, message_handler=collect) as client:
        await client.call_tool("mount", {})
        with anyio.fail_after(5):
            await seen.wait()

    assert len(received) == 1
    assert isinstance(received[0], ServerNotification)
    assert isinstance(received[0].root, ResourceListChangedNotification)


@requirement("prompts:list-changed")
async def test_prompt_list_changed_notification(connect: Connect) -> None:
    """A prompts/list_changed notification sent during a tool call reaches the client's message handler."""
    received: list[IncomingMessage] = []
    seen = anyio.Event()

    async def collect(message: IncomingMessage) -> None:
        received.append(message)
        seen.set()

    server = Server("registry")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name="learn", inputSchema={"type": "object"})]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        assert name == "learn"
        await server.request_context.session.send_prompt_list_changed()
        return [TextContent(type="text", text="learned")]

    @server.list_prompts()
    async def list_prompts() -> list[types.Prompt]:
        """Registered so the prompts capability is advertised; the client never lists prompts."""
        raise NotImplementedError

    async with connect(server, message_handler=collect) as client:
        await client.call_tool("learn", {})
        with anyio.fail_after(5):
            await seen.wait()

    assert len(received) == 1
    assert isinstance(received[0], ServerNotification)
    assert isinstance(received[0].root, PromptListChangedNotification)
