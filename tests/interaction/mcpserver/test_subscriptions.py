"""Client.listen against MCPServer over the connect matrix (2026-07-28)."""

import anyio
import pytest
from mcp_types import PromptListChangedNotification, ResourceListChangedNotification, ToolListChangedNotification

from mcp.client import IncomingMessage
from mcp.client.subscriptions import (
    ListenNotSupportedError,
    PromptsListChanged,
    ResourcesListChanged,
    ResourceUpdated,
    ToolsListChanged,
)
from mcp.server.mcpserver import Context, MCPServer
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


def _notebook() -> MCPServer:
    mcp = MCPServer("notebook")

    @mcp.tool()
    async def touch_tools(ctx: Context) -> str:
        await ctx.notify_tools_changed()
        return "ok"

    @mcp.tool()
    async def edit_note(name: str, ctx: Context) -> str:
        await ctx.notify_resource_updated(f"note://{name}")
        return "saved"

    return mcp


@requirement("subscriptions:listen:client:honored-surfacing")
@requirement("subscriptions:listen:client:iteration")
@requirement("resources:listen:updated")
async def test_listen_surfaces_the_ack_and_iterates_typed_events(connect: Connect) -> None:
    """Entering waits for the ack (honored is set before any event); iteration yields
    only the typed event kinds this stream opted in to."""
    mcp = _notebook()
    async with connect(mcp) as client:
        with anyio.fail_after(10):
            async with client.listen(  # pragma: no branch
                tools_list_changed=True, resource_subscriptions=["note://todo"]
            ) as sub:
                assert sub.honored.tools_list_changed is True
                assert sub.honored.resource_subscriptions == ["note://todo"]

                await client.call_tool("edit_note", {"name": "journal"})  # unsubscribed URI: silent
                await client.call_tool("edit_note", {"name": "todo"})
                assert await anext(sub) == ResourceUpdated(uri="note://todo")

                await client.call_tool("touch_tools", {})
                assert await anext(sub) == ToolsListChanged()


@requirement("tools:listen:list-changed")
@requirement("prompts:listen:list-changed")
@requirement("resources:listen:list-changed")
async def test_each_requested_list_changed_kind_arrives_as_its_typed_event(connect: Connect) -> None:
    """Every list_changed kind the stream asked for is yielded as its typed event, in emission
    order, and the same notification frames still reach message_handler."""
    mcp = MCPServer("catalog")

    @mcp.tool()
    async def reshuffle(ctx: Context) -> str:
        await ctx.notify_tools_changed()
        await ctx.notify_prompts_changed()
        await ctx.notify_resources_changed()
        return "ok"

    teed: list[IncomingMessage] = []
    all_teed = anyio.Event()

    async def record(message: IncomingMessage) -> None:
        teed.append(message)
        if len(teed) == 3:
            all_teed.set()

    async with connect(mcp, message_handler=record) as client:
        with anyio.fail_after(5):
            async with client.listen(
                tools_list_changed=True, prompts_list_changed=True, resources_list_changed=True
            ) as sub:
                await client.call_tool("reshuffle", {})
                events = [await anext(sub) for _ in range(3)]
                await all_teed.wait()
            assert events == [ToolsListChanged(), PromptsListChanged(), ResourcesListChanged()]
            assert [type(n) for n in teed] == [
                ToolListChangedNotification,
                PromptListChangedNotification,
                ResourceListChangedNotification,
            ]


@requirement("subscriptions:listen:client:era-guard")
async def test_listen_on_a_pre_2026_connection_raises_the_typed_steer(connect: Connect) -> None:
    """On 2025-era connections the guard fires before anything touches the wire, steering to the legacy verbs."""
    mcp = _notebook()
    async with connect(mcp) as client:
        with anyio.fail_after(10):
            # Entering is where the guard fires; __aenter__ directly avoids an unreachable with-body.
            with pytest.raises(ListenNotSupportedError) as exc_info:
                await client.listen(tools_list_changed=True).__aenter__()
            assert exc_info.value.negotiated_version == client.session.protocol_version
            assert "subscribe_resource" in str(exc_info.value)
