"""Simple interactive task client demonstrating elicitation and sampling responses."""

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

            result = await session.experimental.call_tool_as_task("confirm_delete", {"filename": "important.txt"})
            task_id = result.task.taskId
            print(f"Task created: {task_id}")

            # get_task_result() delivers elicitation requests and blocks until complete
            final = await session.experimental.get_task_result(task_id, CallToolResult)
            print(f"Result: {get_text(final)}")

            # Demo 2: Sampling (write_haiku)
            print("\n--- Demo 2: Sampling ---")
            print("Calling write_haiku tool...")

            result = await session.experimental.call_tool_as_task("write_haiku", {"topic": "autumn leaves"})
            task_id = result.task.taskId
            print(f"Task created: {task_id}")

            # get_task_result() delivers sampling requests and blocks until complete
            final = await session.experimental.get_task_result(task_id, CallToolResult)
            print(f"Result:\n{get_text(final)}")


@click.command()
@click.option("--url", default="http://localhost:8000/mcp", help="Server URL")
def main(url: str) -> int:
    asyncio.run(run(url))
    return 0


if __name__ == "__main__":
    main()
