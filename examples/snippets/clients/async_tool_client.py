"""
Client example for async tools.

cd to the `examples/snippets` directory and run:
    uv run async-tool-client
"""

import asyncio
import os

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

# Server parameters for async tool example
server_params = StdioServerParameters(
    command="uv",
    args=["run", "server", "async_tool_basic", "stdio"],
    env={"UV_INDEX": os.environ.get("UV_INDEX", "")},
)


async def call_async_tool(session: ClientSession):
    """Demonstrate calling an async tool."""
    print("Calling async tool...")

    result = await session.call_tool("analyze_data", arguments={"dataset": "customer_data.csv"})

    if result.operation:
        token = result.operation.token
        print(f"Operation started with token: {token}")

        # Poll for completion
        while True:
            status = await session.get_operation_status(token)
            print(f"Status: {status.status}")

            if status.status == "completed":
                final_result = await session.get_operation_result(token)
                for content in final_result.result.content:
                    if isinstance(content, types.TextContent):
                        print(f"Result: {content.text}")
                break
            elif status.status == "failed":
                print(f"Operation failed: {status.error}")
                break

            await asyncio.sleep(0.5)


async def run():
    """Run the async tool client example."""
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write, protocol_version="next") as session:
            await session.initialize()
            await call_async_tool(session)


if __name__ == "__main__":
    asyncio.run(run())
