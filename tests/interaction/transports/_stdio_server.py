"""Low-level stdio server for the interaction suite's subprocess test."""

import sys
import warnings

import anyio
import coverage
from mcp_types import (
    CallToolRequestParams,
    CallToolResult,
    EmptyResult,
    ListToolsResult,
    PaginatedRequestParams,
    SetLevelRequestParams,
    TextContent,
    Tool,
)

from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import MCPDeprecationWarning


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
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", MCPDeprecationWarning)
        await ctx.session.send_log_message(level="info", data=f"echoing {text}", logger="echo")  # pyright: ignore[reportDeprecated]
    return CallToolResult(content=[TextContent(text=text)])


async def set_logging_level(ctx: ServerRequestContext, params: SetLevelRequestParams) -> EmptyResult:
    """Registered so the logging capability is advertised; the client never sets a level."""
    raise NotImplementedError


with warnings.catch_warnings():
    warnings.simplefilter("ignore", MCPDeprecationWarning)
    server = Server(  # pyright: ignore[reportDeprecated]
        "stdio-echo", on_list_tools=list_tools, on_call_tool=call_tool, on_set_logging_level=set_logging_level
    )


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
    # Save subprocess coverage before the marker so forced teardown cannot lose it.
    cov = getattr(coverage.process_startup, "coverage", None)
    if cov is not None:  # pragma: no branch
        # Leave nothing for coverage's atexit hook to rewrite if teardown is interrupted.
        cov.stop()
        cov.save()  # pragma: lax no cover - untraced: stop() above already ended measurement
    # The test uses this marker to distinguish clean exit from termination.
    print("stdio-echo: clean exit", file=sys.stderr, flush=True)  # pragma: lax no cover


if __name__ == "__main__":
    anyio.run(main)
