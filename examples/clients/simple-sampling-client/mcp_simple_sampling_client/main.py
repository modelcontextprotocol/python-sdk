"""MCP client demonstrating the sampling feature.

This client connects to an MCP server and provides a sampling callback
so the server can request LLM completions during tool execution.
"""

from __future__ import annotations

import asyncio

import click
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.context import ClientRequestContext
from mcp.client.stdio import stdio_client


async def handle_sampling(
    context: ClientRequestContext,
    params: types.CreateMessageRequestParams,
) -> types.CreateMessageResult:
    """Handle sampling requests from the server.

    In a real application, this would forward the messages to an LLM
    (e.g., OpenAI, Anthropic, Azure OpenAI) and return the response.
    This example uses a simple echo-based response for demonstration.

    Args:
        context: The request context from the client session.
        params: The sampling request parameters including messages,
            max_tokens, temperature, etc.

    Returns:
        A CreateMessageResult with the LLM response.
    """
    # Extract the user's message text
    user_text = ""
    for msg in params.messages:
        if msg.role == "user":
            if isinstance(msg.content, types.TextContent):
                user_text = msg.content.text
            elif isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, types.TextContent):
                        user_text += block.text

    # In a real application, you would call your LLM here:
    #
    #   from openai import AsyncOpenAI
    #   client = AsyncOpenAI()
    #   response = await client.chat.completions.create(
    #       model="gpt-4o",
    #       messages=[{"role": m.role, "content": m.content.text} for m in params.messages],
    #       max_tokens=params.max_tokens,
    #       temperature=params.temperature,
    #   )
    #   return types.CreateMessageResult(
    #       role="assistant",
    #       content=types.TextContent(type="text", text=response.choices[0].message.content),
    #       model=response.model,
    #       stop_reason="endTurn",
    #   )

    # For this demo, we generate a simple response
    if "summary" in user_text.lower() or "summarize" in user_text.lower():
        response_text = "[Demo summary] The text discusses a topic and presents key points."
    elif "sentiment" in user_text.lower():
        response_text = "positive"
    else:
        response_text = f"[Demo response] Processed request with {len(user_text)} characters."

    print(f"  [Sampling] Received request ({len(params.messages)} message(s))")
    print(f"  [Sampling] Responding with: {response_text[:80]}...")

    return types.CreateMessageResult(
        role="assistant",
        content=types.TextContent(type="text", text=response_text),
        model="demo-model",
        stop_reason="endTurn",
    )


async def run() -> None:
    """Connect to the sampling server and demonstrate tool calls."""
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "mcp-simple-sampling"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(
            read,
            write,
            sampling_callback=handle_sampling,
        ) as session:
            await session.initialize()

            # List available tools
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            print(f"Available tools: {tool_names}")

            # Call the summarize tool
            print("\n--- Calling summarize tool ---")
            result = await session.call_tool(
                "summarize",
                {
                    "text": (
                        "The Model Context Protocol (MCP) is an open protocol that "
                        "standardizes how applications provide context to LLMs. MCP "
                        "provides a standardized way to connect AI models to different "
                        "data sources and tools, enabling more powerful AI applications."
                    )
                },
            )
            if result.content and isinstance(result.content[0], types.TextContent):
                print(f"Summary: {result.content[0].text}")

            # Call the analyze_sentiment tool
            print("\n--- Calling analyze_sentiment tool ---")
            result = await session.call_tool(
                "analyze_sentiment",
                {"text": "I absolutely love this new feature! It works great."},
            )
            if result.content and isinstance(result.content[0], types.TextContent):
                print(f"Sentiment: {result.content[0].text}")


@click.command()
def main() -> int:
    asyncio.run(run())
    return 0


if __name__ == "__main__":
    main()
