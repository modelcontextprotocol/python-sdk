"""Low-level Server over stdio for the suite's one subprocess test.

The test launches it via `stdio_client` as `python -m tests.interaction.transports._stdio_server`;
kept separate from the test module so subprocess coverage applies to an importable file while the
test file stays test-functions-only.
"""

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
    # Flush coverage before the clean-exit line the test synchronizes on: the atexit hook alone can
    # overrun the transport's termination grace on slow Windows runners, and the kill then destroys
    # the data file, tripping the 100% gate on this module's subprocess-only lines.
    # The no-branch pragma: under coverage the instance always exists; without it nothing is measured.
    cov = getattr(coverage.process_startup, "coverage", None)
    if cov is not None:  # pragma: no branch
        # stop() ends tracing, making itself the last recordable line, and leaves nothing for
        # coverage's atexit re-save -- so a kill during interpreter teardown cannot tear the file
        # save() wrote (coverage's sqlite journaling is off; a torn rewrite would not roll back).
        cov.stop()
        cov.save()  # pragma: lax no cover - untraced: stop() above already ended measurement
    # Reached only on clean stdin-close exit (a terminated process never prints it); runs after the
    # save by design, hence lax no cover.
    print("stdio-echo: clean exit", file=sys.stderr, flush=True)  # pragma: lax no cover


if __name__ == "__main__":
    anyio.run(main)
