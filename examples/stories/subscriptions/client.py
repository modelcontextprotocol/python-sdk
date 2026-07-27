"""Open a `subscriptions/listen` stream, watch one URI and the tool list, then close it."""

import anyio
import mcp_types as types

from mcp.client import Client
from mcp.client.subscriptions import ResourceUpdated, ToolsListChanged
from stories._harness import Target, run_client


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode) as client:
        before = await client.list_tools()
        assert "search" not in {tool.name for tool in before.tools}

        async with client.listen(tools_list_changed=True, resource_subscriptions=["note://todo"]) as sub:
            # ── entering waited for the ack: the honored filter is already in hand ──
            assert sub.honored.tools_list_changed is True
            assert sub.honored.resource_subscriptions == ["note://todo"]

            # ── exact-URI filtering: an unsubscribed note edit stays silent ──
            await client.call_tool("edit_note", {"name": "journal", "text": "day two"})
            # ── the subscribed URI delivers ──
            await client.call_tool("edit_note", {"name": "todo", "text": "water plants"})
            with anyio.fail_after(10):
                event = await anext(sub)
            assert event == ResourceUpdated(uri="note://todo"), "the journal edit must not have been delivered"

            # ── a runtime tool registration announces itself ──
            await client.call_tool("enable_search", {})
            with anyio.fail_after(10):
                assert await anext(sub) == ToolsListChanged()

        # ── leaving the block closed the stream; the session lives on ──
        tools = await client.list_tools()
        assert "search" in {tool.name for tool in tools.tools}
        result = await client.call_tool("search", {"query": "water"})
        content = result.content[0]
        assert isinstance(content, types.TextContent) and content.text == "todo", result


if __name__ == "__main__":
    run_client(main)
