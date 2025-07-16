"""
Run from the repository root:
uv run examples/snippets/servers/lowlevel/basic.py
"""

import asyncio

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

# Create a server instance
server = Server("example-server")


@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    """List available prompts."""
    return [
        types.Prompt(
            name="example-prompt",
            description="An example prompt template",
            arguments=[types.PromptArgument(name="arg1", description="Example argument", required=True)],
        )
    ]


@server.get_prompt()
async def handle_get_prompt(name: str, arguments: dict[str, str] | None) -> types.GetPromptResult:
    """Get a specific prompt by name."""
    if name != "example-prompt":
        raise ValueError(f"Unknown prompt: {name}")

    arg1_value = (arguments or {}).get("arg1", "default")

    return types.GetPromptResult(
        description="Example prompt",
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(type="text", text=f"Example prompt text with argument: {arg1_value}"),
            )
        ],
    )


async def run():
    """Run the basic low-level server."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="example",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(run())
