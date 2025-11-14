"""
Run from the repository root:
    uv run examples/snippets/clients/task_based_tool_client.py

Prerequisites:
    The task_based_tool server must be running on http://localhost:8000
    Start it with:
        cd examples/snippets && uv run server task_based_tool streamable-http
"""

import asyncio

from mcp import ClientSession, types
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.context import RequestContext
from mcp.shared.request import TaskHandlerOptions


async def elicitation_handler(
    context: RequestContext[ClientSession, None], params: types.ElicitRequestParams
) -> types.ElicitResult | types.ErrorData:
    """
    Handle elicitation requests from the server.

    This handler collects user feedback with a predefined schema including:
    - rating (1-5, required)
    - comments (optional text up to 500 chars)
    - recommend (boolean, required)
    """
    print(f"\n🎯 Elicitation request received: {params.message}")
    print(f"Schema: {params.requestedSchema}")
    await asyncio.sleep(5)

    # In a real application, you would collect this data from the user
    # For this example, we'll return mock data
    feedback_data: dict[str, str | int | float | bool | None] = {
        "rating": 5,
        "comments": "The task execution was excellent and fast!",
        "recommend": True,
    }

    print(f"📝 Returning feedback: {feedback_data}")

    return types.ElicitResult(action="accept", content=feedback_data)


async def main():
    """
    Demonstrate task-based execution with begin_call_tool.

    This example shows how to:
    1. Start a long-running tool call with begin_call_tool()
    2. Get task status updates through callbacks
    3. Wait for the final result with polling
    4. Handle elicitation requests from the server
    """
    # Connect to the task-based tool example server via streamable HTTP
    async with streamablehttp_client("http://localhost:3000/mcp", terminate_on_close=False) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream, elicitation_callback=elicitation_handler) as session:
            # Initialize the connection
            await session.initialize()

            print("Starting task-based tool execution...")

            # Track callback invocations
            task_created = False
            status_updates: list[str] = []

            async def on_task_created() -> None:
                """Called when the task is first created."""
                nonlocal task_created
                task_created = True
                print("✓ Task created on server")

            async def on_task_status(task_result: types.GetTaskResult) -> None:
                """Called whenever the task status is polled."""
                status_updates.append(task_result.status)
                print(f"  Status ({task_result.taskId}): {task_result.status}")

            # Begin the tool call (returns immediately with a PendingRequest)
            print("\nCalling begin_call_tool...")
            # pending_request = session.begin_call_tool(
            #     "collect-user-info",
            #     arguments={"infoType": "feedback"},
            # )
            pending_request = session.begin_call_tool(
                "delay",
                arguments={},
            )

            print("Tool call initiated! Now waiting for result with task polling...\n")

            # Wait for the result with task callbacks
            result = await pending_request.result(
                TaskHandlerOptions(on_task_created=on_task_created, on_task_status=on_task_status)
            )

            # Display the result
            print("\n✓ Tool execution completed!")
            if result.content:
                content_block = result.content[0]
                if isinstance(content_block, types.TextContent):
                    print(f"Result: {content_block.text}")
                else:
                    print(f"Result: {content_block}")
            else:
                print("Result: No content")

            # Show callback statistics
            print("\nTask callbacks:")
            print(f"  - Task created callback: {'Yes' if task_created else 'No'}")
            print(f"  - Status updates received: {len(status_updates)}")
            if status_updates:
                print(f"  - Final status: {status_updates[-1]}")


if __name__ == "__main__":
    asyncio.run(main())
