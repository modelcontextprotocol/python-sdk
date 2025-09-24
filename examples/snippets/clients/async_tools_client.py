"""
Client example showing how to use async tools.

cd to the `examples/snippets` directory and run:
    uv run async-tools-client
    uv run async-tools-client --protocol=latest  # backwards compatible mode
    uv run async-tools-client --protocol=next    # async tools mode
"""

import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

# Create server parameters for stdio connection
server_params = StdioServerParameters(
    command="uv",  # Using uv to run the server
    args=["run", "server", "async_tools", "stdio"],
    env={"UV_INDEX": os.environ.get("UV_INDEX", "")},
)


async def demonstrate_sync_tool(session: ClientSession):
    """Demonstrate calling a synchronous tool."""
    print("\n=== Synchronous Tool Demo ===")

    result = await session.call_tool("sync_tool", arguments={"x": 21})

    # Print the result
    for content in result.content:
        if isinstance(content, types.TextContent):
            print(f"Sync tool result: {content.text}")


async def demonstrate_async_tool(session: ClientSession):
    """Demonstrate calling an async-only tool."""
    print("\n=== Asynchronous Tool Demo ===")

    # Call the async tool
    result = await session.call_tool("async_only_tool", arguments={"data": "sample dataset"})

    if result.operation:
        token = result.operation.token
        print(f"Async operation started with token: {token}")

        # Poll for status updates
        while True:
            status = await session.get_operation_status(token)
            print(f"Status: {status.status}")

            if status.status == "completed":
                # Get the final result
                final_result = await session.get_operation_result(token)
                for content in final_result.result.content:
                    if isinstance(content, types.TextContent):
                        print(f"Final result: {content.text}")
                break
            elif status.status == "failed":
                print(f"Operation failed: {status.error}")
                break
            elif status.status in ("canceled", "unknown"):
                print(f"Operation ended with status: {status.status}")
                break

            # Wait before polling again
            await asyncio.sleep(1)
    else:
        # Synchronous result (shouldn't happen for async-only tools)
        for content in result.content:
            if isinstance(content, types.TextContent):
                print(f"Unexpected sync result: {content.text}")


async def demonstrate_hybrid_tool(session: ClientSession):
    """Demonstrate calling a hybrid tool in both modes."""
    print("\n=== Hybrid Tool Demo ===")

    # Call hybrid tool (will be sync by default for compatibility)
    result = await session.call_tool("hybrid_tool", arguments={"message": "hello world"})

    for content in result.content:
        if isinstance(content, types.TextContent):
            print(f"Hybrid tool result: {content.text}")


async def demonstrate_batch_processing(session: ClientSession):
    """Demonstrate batch processing with progress updates."""
    print("\n=== Batch Processing Demo ===")

    items = ["apple", "banana", "cherry", "date", "elderberry"]

    # Define progress callback
    async def progress_callback(progress: float, total: float | None, message: str | None) -> None:
        progress_pct = int(progress * 100) if progress else 0
        total_str = f"/{int(total * 100)}%" if total else ""
        message_str = f" - {message}" if message else ""
        print(f"Progress: {progress_pct}{total_str}{message_str}")

    result = await session.call_tool(
        "batch_operation_tool", arguments={"items": items}, progress_callback=progress_callback
    )

    if result.operation:
        token = result.operation.token
        print(f"Batch operation started with token: {token}")

        # Poll for status
        while True:
            status = await session.get_operation_status(token)
            print(f"Status: {status.status}")

            if status.status == "completed":
                # Get the final result
                final_result = await session.get_operation_result(token)

                # Check for structured result
                if final_result.result.structuredContent:
                    print(f"Structured result: {final_result.result.structuredContent}")

                # Also show text content
                for content in final_result.result.content:
                    if isinstance(content, types.TextContent):
                        print(f"Text result: {content.text}")
                break
            elif status.status == "failed":
                print(f"Operation failed: {status.error}")
                break
            elif status.status in ("canceled", "unknown"):
                print(f"Operation ended with status: {status.status}")
                break

            # Wait before polling again
            await asyncio.sleep(0.5)
    else:
        print("Unexpected: batch operation returned synchronous result")


async def demonstrate_data_processing(session: ClientSession):
    """Demonstrate complex data processing pipeline."""
    print("\n=== Data Processing Pipeline Demo ===")

    operations = ["validate", "clean", "transform", "analyze", "export"]
    result = await session.call_tool(
        "data_processing_tool", arguments={"dataset": "customer_data.csv", "operations": operations}
    )

    if result.operation:
        token = result.operation.token
        print(f"Data processing started with token: {token}")

        # Poll for completion
        while True:
            status = await session.get_operation_status(token)
            print(f"Status: {status.status}")

            if status.status == "completed":
                final_result = await session.get_operation_result(token)

                # Show structured result if available
                if final_result.result.structuredContent:
                    print("Processing results:")
                    for op, result_text in final_result.result.structuredContent.items():
                        print(f"  {op}: {result_text}")
                break
            elif status.status == "failed":
                print(f"Processing failed: {status.error}")
                break
            elif status.status in ("canceled", "unknown"):
                print(f"Processing ended with status: {status.status}")
                break

            await asyncio.sleep(0.8)


async def run():
    """Run all async tool demonstrations."""
    # Determine protocol version from command line
    protocol_version = "next"  # Default to next for async tools
    if len(sys.argv) > 1:
        if "--protocol=latest" in sys.argv:
            protocol_version = "2025-06-18"  # Latest stable protocol
        elif "--protocol=next" in sys.argv:
            protocol_version = "next"  # Development protocol version with async tools

    print(f"Using protocol version: {protocol_version}")
    print()

    async with stdio_client(server_params) as (read, write):
        # Use configured protocol version
        async with ClientSession(read, write, protocol_version=protocol_version) as session:
            # Initialize the connection
            await session.initialize()

            # List available tools to see invocation modes
            tools = await session.list_tools()
            print("Available tools:")
            for tool in tools.tools:
                invocation_mode = getattr(tool, "invocationMode", "sync")
                print(f"  - {tool.name}: {tool.description} (mode: {invocation_mode})")

            # Demonstrate different tool types
            await demonstrate_sync_tool(session)
            await demonstrate_hybrid_tool(session)
            await demonstrate_async_tool(session)
            await demonstrate_batch_processing(session)
            await demonstrate_data_processing(session)

            print("\n=== All demonstrations complete! ===")


def main():
    """Entry point for the async tools client."""
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: async-tools-client [--protocol=latest|next]")
        print()
        print("Protocol versions:")
        print("  --protocol=latest  Use stable protocol (only sync/hybrid tools visible)")
        print("  --protocol=next    Use development protocol (all async tools visible)")
        print()
        print("Default: --protocol=next")
        return

    asyncio.run(run())


if __name__ == "__main__":
    main()
