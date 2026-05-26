"""A real low-level Server over the stdio transport, for the suite's one subprocess test.

Runnable as `python -m tests.interaction.transports._stdio_server` from the repo root; the test
launches it that way via `stdio_client`. Kept separate from the test module so the server lives in
its own importable file (subprocess coverage applies) while the test file follows the suite's
test-only-functions convention.
"""

import sys

import anyio

from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)


async def list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(
        tools=[
            Tool(
                name="echo",
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            )
        ]
    )


async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
    assert params.name == "echo"
    assert params.arguments is not None
    text = params.arguments["text"]
    await ctx.session.send_log_message(level="info", data=f"echoing {text}", logger="echo")
    return CallToolResult(content=[TextContent(text=text)])


server = Server("stdio-echo", on_list_tools=list_tools, on_call_tool=call_tool)


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
    # Reached only when the run loop exits because stdin closed; if the process were terminated
    # the test's stderr capture would not see this line.
    print("stdio-echo: clean exit", file=sys.stderr, flush=True)


if __name__ == "__main__":
    anyio.run(main)
