import anyio
import pytest
from pydantic import AnyUrl

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session as create_session


@pytest.mark.anyio
async def test_messages_are_executed_concurrently_tools():
    server = FastMCP("test")
    event = anyio.Event()
    tool_started = anyio.Event()
    call_order: list[str] = []

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


@pytest.mark.anyio
async def test_messages_are_executed_concurrently_tools_and_resources():
    server = FastMCP("test")
    event = anyio.Event()
    tool_started = anyio.Event()
    call_order: list[str] = []

    @server.tool("sleep")
    async def sleep_tool():
        call_order.append("waiting_for_event")
        tool_started.set()
        await event.wait()
        call_order.append("tool_end")
        return "done"

    @server.resource("slow://slow_resource")
    async def slow_resource():
        # Wait for tool to start before setting the event
        await tool_started.wait()
        event.set()
        call_order.append("resource_end")
        return "slow"

    async with create_session(server._mcp_server) as client_session:
        # First tool will wait on event, second will set it
        async with anyio.create_task_group() as tg:
            # Start the tool first (it will wait on event)
            tg.start_soon(client_session.call_tool, "sleep")
            # Then the resource (it will set the event)
            tg.start_soon(client_session.read_resource, AnyUrl("slow://slow_resource"))

        # Verify that both ran concurrently
        assert call_order == [
            "waiting_for_event",
            "resource_end",
            "tool_end",
        ], f"Expected concurrent execution, but got: {call_order}"
