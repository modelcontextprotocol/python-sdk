"""Prompt client example: list, inspect, and get prompts from a server.

cd to the `examples/snippets` directory and run:
    uv run prompt-client
"""

import asyncio
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

server_params = StdioServerParameters(
    command="uv",
    args=["run", "server", "prompt_server", "stdio"],
    env={"UV_INDEX": os.environ.get("UV_INDEX", "")},
)


async def run():
    """Connect to the prompt server and exercise the prompts API."""
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. Discover which prompts the server exposes
            result = await session.list_prompts()
            print("Available prompts:")
            for prompt in result.prompts:
                args = ", ".join(f"{a.name}{'?' if not a.required else ''}" for a in (prompt.arguments or []))
                print(f"  - {prompt.name}({args}): {prompt.description}")

            # 2. Fetch the single-string prompt and print its message
            review = await session.get_prompt(
                "review_code",
                arguments={"code": "def add(a, b):\n    return a + b"},
            )
            print("\nreview_code prompt messages:")
            for msg in review.messages:
                text = msg.content.text if isinstance(msg.content, TextContent) else str(msg.content)
                print(f"  [{msg.role}] {text}")

            # 3. Fetch the multi-turn prompt and print each message in the thread
            debug = await session.get_prompt(
                "debug_error",
                arguments={"error": "NameError: name 'x' is not defined"},
            )
            print("\ndebug_error prompt messages:")
            for msg in debug.messages:
                text = msg.content.text if isinstance(msg.content, TextContent) else str(msg.content)
                print(f"  [{msg.role}] {text}")


def main():
    """Entry point for the prompt client."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
