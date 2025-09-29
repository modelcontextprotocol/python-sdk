"""
Client example for async tools with elicitation.

cd to the `examples/snippets` directory and run:
    uv run async-elicitation-client
"""

import asyncio
import os

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.shared.context import RequestContext

# Server parameters for async elicitation example
server_params = StdioServerParameters(
    command="uv",
    args=["run", "server", "async_tool_elicitation", "stdio"],
    env={"UV_INDEX": os.environ.get("UV_INDEX", "")},
)


async def elicitation_callback(context: RequestContext[ClientSession, None], params: types.ElicitRequestParams):
    """Handle elicitation requests from the server."""
    print(f"Server is asking: {params.message}")

    # Handle different types of elicitation
    if "data_migration" in params.message:
        print("Client responding: Continue with high priority")
        return types.ElicitResult(
            action="accept",
            content={"continue_processing": True, "priority_level": "high"},
        )
    elif "file operation" in params.message.lower() or "confirm" in params.message.lower():
        print("Client responding: Confirm operation with backup")
        return types.ElicitResult(
            action="accept",
            content={"confirm_operation": True, "backup_first": True},
        )
    elif "How should we proceed" in params.message:
        print("Client responding: Continue with normal priority")
        return types.ElicitResult(
            action="accept",
            content={"continue_processing": True, "priority_level": "normal"},
        )
    else:
        print("Client responding: Decline")
        return types.ElicitResult(action="decline")


async def test_process_with_confirmation(session: ClientSession):
    """Test process that requires user confirmation."""
    print("Testing process with confirmation...")

    result = await session.call_tool("process_with_confirmation", {"operation": "data_migration"})

    if result.operation:
        token = result.operation.token
        print(f"Operation started with token: {token}")

        while True:
            status = await session.get_operation_status(token)
            if status.status == "completed":
                final_result = await session.get_operation_result(token)
                for content in final_result.result.content:
                    if isinstance(content, types.TextContent):
                        print(f"Result: {content.text}")
                break
            elif status.status == "failed":
                print(f"Operation failed: {status.error}")
                break

            await asyncio.sleep(0.3)


async def test_file_operation(session: ClientSession):
    """Test file operation with confirmation."""
    print("\nTesting file operation...")

    result = await session.call_tool(
        "file_operation", {"file_path": "/path/to/important_file.txt", "operation_type": "delete"}
    )

    if result.operation:
        token = result.operation.token
        print(f"File operation started with token: {token}")

        while True:
            status = await session.get_operation_status(token)
            if status.status == "completed":
                final_result = await session.get_operation_result(token)
                for content in final_result.result.content:
                    if isinstance(content, types.TextContent):
                        print(f"Result: {content.text}")
                break
            elif status.status == "failed":
                print(f"File operation failed: {status.error}")
                break

            await asyncio.sleep(0.3)


async def run():
    """Run the async elicitation client example."""
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(
            read, write, protocol_version="next", elicitation_callback=elicitation_callback
        ) as session:
            await session.initialize()

            await test_process_with_confirmation(session)
            await test_file_operation(session)

            print("\nElicitation examples complete!")


if __name__ == "__main__":
    asyncio.run(run())
