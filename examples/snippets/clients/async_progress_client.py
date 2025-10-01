"""
Client example for async tools with progress notifications.

cd to the `examples/snippets` directory and run:
    uv run async-progress-client
"""

import os

import anyio

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

# Server parameters for async progress example
server_params = StdioServerParameters(
    command="uv",
    args=["run", "server", "async_tool_progress", "stdio"],
    env={"UV_INDEX": os.environ.get("UV_INDEX", "")},
)


async def test_batch_processing(session: ClientSession):
    """Test batch processing with progress notifications."""
    print("Testing batch processing with progress notifications...")

    items = ["apple", "banana", "cherry", "date", "elderberry"]
    progress_updates: list[tuple[float, float | None, str | None]] = []

    async def progress_callback(progress: float, total: float | None, message: str | None) -> None:
        progress_pct = int(progress * 100) if progress else 0
        total_str = f"/{int(total * 100)}%" if total else ""
        message_str = f" - {message}" if message else ""
        print(f"Progress: {progress_pct}{total_str}{message_str}")
        progress_updates.append((progress, total, message))

    result = await session.call_tool("batch_process", arguments={"items": items}, progress_callback=progress_callback)

    if result.operation:
        token = result.operation.token
        print(f"Batch operation started with token: {token}")

        # Poll for completion
        while True:
            status = await session.get_operation_status(token)
            if status.status == "completed":
                final_result = await session.get_operation_result(token)

                # Show structured result
                if final_result.result.structuredContent:
                    print(f"Structured result: {final_result.result.structuredContent}")

                # Show text content
                for content in final_result.result.content:
                    if isinstance(content, types.TextContent):
                        print(f"Text result: {content.text}")
                break
            elif status.status == "failed":
                print(f"Operation failed: {status.error}")
                break

            await anyio.sleep(0.3)

    print(f"Received {len(progress_updates)} progress updates")


async def test_data_pipeline(session: ClientSession):
    """Test data pipeline with progress tracking."""
    print("\nTesting data pipeline...")

    operations = ["validate", "clean", "transform", "analyze", "export"]

    result = await session.call_tool(
        "data_pipeline", arguments={"dataset": "customer_data.csv", "operations": operations}
    )

    if result.operation:
        token = result.operation.token
        print(f"Pipeline started with token: {token}")

        while True:
            status = await session.get_operation_status(token)
            if status.status == "completed":
                final_result = await session.get_operation_result(token)

                if final_result.result.structuredContent:
                    print("Pipeline results:")
                    for op, result_text in final_result.result.structuredContent.items():
                        print(f"  {op}: {result_text}")
                break
            elif status.status == "failed":
                print(f"Pipeline failed: {status.error}")
                break

            await anyio.sleep(0.3)


async def run():
    """Run the async progress client example."""
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write, protocol_version="next") as session:
            await session.initialize()

            await test_batch_processing(session)
            await test_data_pipeline(session)

            print("\nProgress notification examples complete!")


if __name__ == "__main__":
    anyio.run(run)
