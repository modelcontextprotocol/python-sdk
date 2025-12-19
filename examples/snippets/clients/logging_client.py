"""
cd to the `examples/snippets/clients` directory and run:
    uv run logging-client
"""

import asyncio
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import LoggingMessageNotificationParams

# Create server parameters for stdio connection
server_params = StdioServerParameters(
    command="uv",  # Using uv to run the server
    args=["run", "server", "logging", "stdio"],  # We're already in snippets dir
    env={"UV_INDEX": os.environ.get("UV_INDEX", "")},
)


async def logging_callback(params: LoggingMessageNotificationParams):
    print(f"Log Level: {params.level}, Message: {params.data}")


async def run():
    fds = os.pipe()
    reader = os.fdopen(fds[0], "r")
    writer = os.fdopen(fds[1], "w")
    async with stdio_client(server_params, errlog=writer) as (read, write):
        async with ClientSession(read, write, logging_callback=logging_callback) as session:
            await session.initialize()

            await session.list_tools()
            await session.call_tool("log", arguments={})
    writer.close()
    print("Captured stderr logs:")
    print(reader.read())


def main():
    """Entry point for the client script."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
