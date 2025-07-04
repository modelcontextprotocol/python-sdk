import anyio
import pytest

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session as create_session


@pytest.mark.anyio
async def test_messages_are_executed_concurrently():
    server = FastMCP("test")
    event = anyio.Event()
    tool_started = anyio.Event()
    call_order = []

    @server.tool("sleep")
    async def sleep_tool():
        call_order.append("waiting_for_event")
        tool_started.set()
        await event.wait()
        call_order.append("tool_end")
        return "done"

    @server.tool("trigger")
    async def trigger():
        # Wait for tool to start before setting the event
        await tool_started.wait()
        call_order.append("trigger_started")
        event.set()
        call_order.append("trigger_end")
        return "slow"

    async with create_session(server._mcp_server) as client_session:
        # First tool will wait on event, second will set it
        async with anyio.create_task_group() as tg:
            # Start the tool first (it will wait on event)
            tg.start_soon(client_session.call_tool, "sleep")
            # Then the trigger tool will set the event to allow the first tool to continue
            await client_session.call_tool("trigger")

        # Verify that both ran concurrently
        assert call_order == [
            "waiting_for_event",
            "trigger_started",
            "trigger_end",
            "tool_end",
        ], f"Expected concurrent execution, but got: {call_order}"
