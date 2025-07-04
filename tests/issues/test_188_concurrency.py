import anyio
import pytest
from pydantic import AnyUrl

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session as create_session

_resource_name = "slow://slow_resource"


@pytest.mark.anyio
async def test_messages_are_executed_concurrently():
    server = FastMCP("test")
    event = anyio.Event()
    call_order = []

    @server.tool("sleep")
    async def sleep_tool():
        call_order.append("waiting_for_event")
        await event.wait()
        call_order.append("tool_end")
        return "done"

    @server.resource(_resource_name)
    async def slow_resource():
        # Set event immediately
        event.set()
        call_order.append("resource_end")
        return "slow"

    async with create_session(server._mcp_server) as client_session:
        # Start both requests concurrently
        async with anyio.create_task_group() as tg:
            tg.start_soon(client_session.call_tool, "sleep")
            tg.start_soon(client_session.read_resource, AnyUrl(_resource_name))

        # Verify that both ran concurrently
        assert call_order == [
            "waiting_for_event",
            "resource_end",
            "tool_end",
        ], f"Expected concurrent execution, but got: {call_order}"
