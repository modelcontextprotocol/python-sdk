"""Simple interactive task client demonstrating elicitation and sampling responses.

This example demonstrates the spec-compliant polling pattern:
1. Poll tasks/get watching for status changes
2. On input_required, call tasks/result to receive elicitation/sampling requests
3. Continue until terminal status, then retrieve final result
"""

import asyncio
from typing import Any

import click
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.context import RequestContext
from mcp.types import (
    CallToolResult,
    CreateMessageRequestParams,
    CreateMessageResult,
    ElicitRequestParams,
    ElicitResult,
    TextContent,
)


async def elicitation_callback(
    context: RequestContext[ClientSession, Any],
    params: ElicitRequestParams,
) -> ElicitResult:
    """Handle elicitation requests from the server."""
    print(f"\n[Elicitation] Server asks: {params.message}")

    # Simple terminal prompt
    response = input("Your response (y/n): ").strip().lower()
    confirmed = response in ("y", "yes", "true", "1")

    print(f"[Elicitation] Responding with: confirm={confirmed}")
    return ElicitResult(action="accept", content={"confirm": confirmed})


async def sampling_callback(
    context: RequestContext[ClientSession, Any],
    params: CreateMessageRequestParams,
) -> CreateMessageResult:
    """Handle sampling requests from the server."""
    # Get the prompt from the first message
    prompt = "unknown"
    if params.messages:
        content = params.messages[0].content
        if isinstance(content, TextContent):
            prompt = content.text

    print(f"\n[Sampling] Server requests LLM completion for: {prompt}")

    # Return a hardcoded haiku (in real use, call your LLM here)
    haiku = """Cherry blossoms fall
Softly on the quiet pond
Spring whispers goodbye"""

    print("[Sampling] Responding with haiku")
    return CreateMessageResult(
        model="mock-haiku-model",
        role="assistant",
        content=TextContent(type="text", text=haiku),
    )


def get_text(result: CallToolResult) -> str:
    """Extract text from a CallToolResult."""
    if result.content and isinstance(result.content[0], TextContent):
        return result.content[0].text
    return "(no text)"


async def run(url: str) -> None:
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(
            read,
            write,
            elicitation_callback=elicitation_callback,
            sampling_callback=sampling_callback,
        ) as session:
            await session.initialize()

            # List tools
            tools = await session.list_tools()
            print(f"Available tools: {[t.name for t in tools.tools]}")

            # Demo 1: Elicitation (confirm_delete)
            print("\n--- Demo 1: Elicitation ---")
            print("Calling confirm_delete tool...")

            elicit_task = await session.experimental.call_tool_as_task("confirm_delete", {"filename": "important.txt"})
            elicit_task_id = elicit_task.task.taskId
            print(f"Task created: {elicit_task_id}")

            # Poll until terminal, calling tasks/result on input_required
            async for status in session.experimental.poll_task(elicit_task_id):
                print(f"[Poll] Status: {status.status}")
                if status.status == "input_required":
                    # Server needs input - tasks/result delivers the elicitation request
                    elicit_result = await session.experimental.get_task_result(elicit_task_id, CallToolResult)
                    break
            else:
                # poll_task exited due to terminal status
                elicit_result = await session.experimental.get_task_result(elicit_task_id, CallToolResult)

            print(f"Result: {get_text(elicit_result)}")

            # Demo 2: Sampling (write_haiku)
            print("\n--- Demo 2: Sampling ---")
            print("Calling write_haiku tool...")

            sampling_task = await session.experimental.call_tool_as_task("write_haiku", {"topic": "autumn leaves"})
            sampling_task_id = sampling_task.task.taskId
            print(f"Task created: {sampling_task_id}")

            # Poll until terminal, calling tasks/result on input_required
            async for status in session.experimental.poll_task(sampling_task_id):
                print(f"[Poll] Status: {status.status}")
                if status.status == "input_required":
                    sampling_result = await session.experimental.get_task_result(sampling_task_id, CallToolResult)
                    break
            else:
                sampling_result = await session.experimental.get_task_result(sampling_task_id, CallToolResult)

            print(f"Result:\n{get_text(sampling_result)}")


@click.command()
@click.option("--url", default="http://localhost:8000/mcp", help="Server URL")
def main(url: str) -> int:
    asyncio.run(run(url))
    return 0


if __name__ == "__main__":
    main()
