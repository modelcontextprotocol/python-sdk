"""Simple task client demonstrating MCP tasks polling over streamable HTTP."""

import asyncio

import click
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    ClientRequest,
    CreateTaskResult,
    TaskMetadata,
    TextContent,
)


async def run(url: str) -> None:
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # List tools
            tools = await session.list_tools()
            print(f"Available tools: {[t.name for t in tools.tools]}")

            # Call the tool as a task
            print("\nCalling tool as a task...")

            # TODO: make helper for this
            result = await session.send_request(
                ClientRequest(
                    CallToolRequest(
                        params=CallToolRequestParams(
                            name="long_running_task",
                            arguments={},
                            task=TaskMetadata(ttl=60000),
                        )
                    )
                ),
                CreateTaskResult,
            )
            task_id = result.task.taskId
            print(f"Task created: {task_id}")

            # Poll until done
            while True:
                status = await session.experimental.get_task(task_id)
                print(f"  Status: {status.status} - {status.statusMessage or ''}")

                if status.status == "completed":
                    break
                elif status.status in ("failed", "cancelled"):
                    print(f"Task ended with status: {status.status}")
                    return

                await asyncio.sleep(0.5)

            # Get the result
            task_result = await session.experimental.get_task_result(task_id, CallToolResult)
            content = task_result.content[0]
            if isinstance(content, TextContent):
                print(f"\nResult: {content.text}")


@click.command()
@click.option("--url", default="http://localhost:8000/mcp", help="Server URL")
def main(url: str) -> int:
    asyncio.run(run(url))
    return 0


if __name__ == "__main__":
    main()
