"""Client.listen against MCPServer over the connect matrix (2026-07-28)."""

import anyio
import pytest

from mcp.client.subscriptions import ListenNotSupportedError, ResourceUpdated, ToolsListChanged
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
