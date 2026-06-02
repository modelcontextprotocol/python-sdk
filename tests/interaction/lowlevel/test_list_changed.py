"""List-changed notifications from the low-level Server, driven through the public Client API.

``send_*_list_changed`` does not take a ``related_request_id``, so over streamable HTTP the
notification routes to the standalone GET stream and is not guaranteed to arrive before the tool
result on its POST stream. Tests therefore wait on an event the collector sets, the same pattern
as ``transports/test_streamable_http.py::test_unrelated_server_messages_arrive_on_the_standalone_stream``.
The collector still records every message it receives, so the snapshot also proves nothing else
was delivered.

The servers register the parent capability (resources/prompts) so that part of the spec's
precondition holds, but the ``listChanged`` sub-capability stays ``False``: ``NotificationOptions``
is not threaded through any of the suite's connection paths. The tests therefore rely on the
recorded ``lifecycle:capability:server-not-advertised`` divergence and will need updating
alongside the fix that introduces capability gating.
"""

import anyio
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    CallToolResult,
    PromptListChangedNotification,
    ResourceListChangedNotification,
    TextContent,
    ToolListChangedNotification,
)

from mcp.server import Server, ServerRequestContext
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

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="install", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "install"
        await ctx.session.send_tool_list_changed()
        return CallToolResult(content=[TextContent(text="installed")])

    server = Server("registry", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server, message_handler=collect) as client:
        await client.call_tool("install", {})
        with anyio.fail_after(5):
            await seen.wait()

    assert received == snapshot([ToolListChangedNotification()])


@requirement("resources:list-changed")
async def test_resource_list_changed_notification(connect: Connect) -> None:
    """A resources/list_changed notification sent during a tool call reaches the client's message handler."""
    received: list[IncomingMessage] = []
    seen = anyio.Event()

    async def collect(message: IncomingMessage) -> None:
        received.append(message)
        seen.set()

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="mount", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "mount"
        await ctx.session.send_resource_list_changed()
        return CallToolResult(content=[TextContent(text="mounted")])

    async def list_resources(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListResourcesResult:
        """Registered so the resources capability is advertised; the client never lists resources."""
        raise NotImplementedError

    server = Server("registry", on_list_tools=list_tools, on_call_tool=call_tool, on_list_resources=list_resources)

    async with connect(server, message_handler=collect) as client:
        await client.call_tool("mount", {})
        with anyio.fail_after(5):
            await seen.wait()

    assert received == snapshot([ResourceListChangedNotification()])


@requirement("prompts:list-changed")
async def test_prompt_list_changed_notification(connect: Connect) -> None:
    """A prompts/list_changed notification sent during a tool call reaches the client's message handler."""
    received: list[IncomingMessage] = []
    seen = anyio.Event()

    async def collect(message: IncomingMessage) -> None:
        received.append(message)
        seen.set()

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="learn", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "learn"
        await ctx.session.send_prompt_list_changed()
        return CallToolResult(content=[TextContent(text="learned")])

    async def list_prompts(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListPromptsResult:
        """Registered so the prompts capability is advertised; the client never lists prompts."""
        raise NotImplementedError

    server = Server("registry", on_list_tools=list_tools, on_call_tool=call_tool, on_list_prompts=list_prompts)

    async with connect(server, message_handler=collect) as client:
        await client.call_tool("learn", {})
        with anyio.fail_after(5):
            await seen.wait()

    assert received == snapshot([PromptListChangedNotification()])
