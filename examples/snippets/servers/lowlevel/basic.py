"""Run from the repository root:
uv run examples/snippets/servers/lowlevel/basic.py
"""

import asyncio
from typing import Any

import mcp.server.stdio
from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions


async def handle_list_prompts(
    ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
) -> types.ListPromptsResult:
    """List available prompts."""
    return types.ListPromptsResult(
        prompts=[
            types.Prompt(
                name="example-prompt",
                description="An example prompt template",
                arguments=[types.PromptArgument(name="arg1", description="Example argument", required=True)],
            )
        ]
    )


async def handle_get_prompt(
    ctx: ServerRequestContext[Any], params: types.GetPromptRequestParams
) -> types.GetPromptResult:
    """Get a specific prompt by name."""
    if params.name != "example-prompt":
        raise ValueError(f"Unknown prompt: {params.name}")

    arg1_value = (params.arguments or {}).get("arg1", "default")

    return types.GetPromptResult(
        description="Example prompt",
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(type="text", text=f"Example prompt text with argument: {arg1_value}"),
            )
        ],
    )


# Create a server instance
server = Server(
    "example-server",
    on_list_prompts=handle_list_prompts,
    on_get_prompt=handle_get_prompt,
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
