import anyio
import pytest
from pydantic import AnyUrl

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import (
    create_connected_server_and_client_session as create_session,
)

_sleep_time_seconds = 0.01
_resource_name = "slow://slow_resource"


@pytest.mark.anyio
async def test_messages_are_executed_concurrently():
    server = FastMCP("test")
    call_timestamps = []

    @server.tool("sleep")
    async def sleep_tool():
        call_timestamps.append(("tool_start_time", anyio.current_time()))
        await anyio.sleep(_sleep_time_seconds)
        call_timestamps.append(("tool_end_time", anyio.current_time()))
        return "done"

    @server.resource(_resource_name)
    async def slow_resource():
        call_timestamps.append(("resource_start_time", anyio.current_time()))
        await anyio.sleep(_sleep_time_seconds)
        call_timestamps.append(("resource_end_time", anyio.current_time()))
        return "slow"

    async with create_session(server._mcp_server) as client_session:
        async with anyio.create_task_group() as tg:
            for _ in range(10):
                tg.start_soon(client_session.call_tool, "sleep")
                tg.start_soon(client_session.read_resource, AnyUrl(_resource_name))

        active_calls = 0
        max_concurrent_calls = 0
        for call_type, _ in sorted(call_timestamps, key=lambda x: x[1]):
            if "start" in call_type:
                active_calls += 1
                max_concurrent_calls = max(max_concurrent_calls, active_calls)
            else:
                active_calls -= 1
        print(f"Max concurrent calls: {max_concurrent_calls}")
        assert max_concurrent_calls > 1, "No concurrent calls were executed"


def main():
    anyio.run(test_messages_are_executed_concurrently)


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.DEBUG)

    main()
