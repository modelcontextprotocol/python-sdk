import anyio
import pytest

from mcp import Client
from mcp.server.mcpserver import MCPServer


@pytest.mark.anyio
async def test_messages_are_executed_concurrently_tools():
    server = MCPServer("test")
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
        await tool_started.wait()
        call_order.append("trigger_started")
        event.set()
        call_order.append("trigger_end")
        return "slow"

    async with Client(server) as client_session:
        async with anyio.create_task_group() as tg:
            tg.start_soon(client_session.call_tool, "sleep")
            await client_session.call_tool("trigger")

        assert call_order == [
            "waiting_for_event",
            "trigger_started",
            "trigger_end",
            "tool_end",
        ], f"Expected concurrent execution, but got: {call_order}"


@pytest.mark.anyio
async def test_messages_are_executed_concurrently_tools_and_resources():
    server = MCPServer("test")
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
        await tool_started.wait()
        event.set()
        call_order.append("resource_end")
        return "slow"

    async with Client(server) as client_session:
        async with anyio.create_task_group() as tg:
            tg.start_soon(client_session.call_tool, "sleep")
            tg.start_soon(client_session.read_resource, "slow://slow_resource")

        assert call_order == [
            "waiting_for_event",
            "resource_end",
            "tool_end",
        ], f"Expected concurrent execution, but got: {call_order}"
