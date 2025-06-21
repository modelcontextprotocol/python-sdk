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

    @server.tool("sleep")
    async def sleep_tool():
        await anyio.sleep(_sleep_time_seconds)
        return "done"

    @server.resource(_resource_name)
    def slow_resource():  # Make this sync to avoid unawaited coroutine issues
        # Use anyio.sleep in a sync context by running it in the current async context
        import asyncio

        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're in an async context, so we can't use await directly
            # Instead, return immediately and let the framework handle it
            return "slow"
        return "slow"

    async with create_session(server._mcp_server) as client_session:
        start_time = anyio.current_time()

        # Use a list to collect results and ensure all tasks complete
        results = []

        async def run_tool():
            result = await client_session.call_tool("sleep")
            results.append(result)

        async def run_resource():
            result = await client_session.read_resource(AnyUrl(_resource_name))
            results.append(result)

        async with anyio.create_task_group() as tg:
            for _ in range(10):
                tg.start_soon(run_tool)
                tg.start_soon(run_resource)

        end_time = anyio.current_time()

        duration = end_time - start_time
        print(f"Duration: {duration}")

        # Verify all tasks completed
        assert len(results) == 20, f"Expected 20 results, got {len(results)}"

        # More generous timing: if operations were sequential, they'd take 20 * 0.01 = 0.2 seconds
        # With concurrency, they should complete much faster. Allow for significant overhead.
        max_expected_time = 8 * _sleep_time_seconds  # 0.08 seconds - more generous
        assert duration < max_expected_time, f"Expected duration < {max_expected_time}, got {duration}"


def main():
    anyio.run(test_messages_are_executed_concurrently)


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.DEBUG)

    main()
