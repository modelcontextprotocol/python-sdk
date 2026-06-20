"""A real low-level Server over the stdio transport, for the suite's one subprocess test.

Runnable as `python -m tests.interaction.transports._stdio_server` from the repo root; the test
launches it that way via `stdio_client`. Kept separate from the test module so the server lives in
its own importable file (subprocess coverage applies) while the test file follows the suite's
test-only-functions convention.
"""

import sys

import anyio
import coverage

from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    EmptyResult,
    ListToolsResult,
    PaginatedRequestParams,
    SetLevelRequestParams,  # pyright: ignore[reportDeprecated]
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


async def set_logging_level(ctx: ServerRequestContext, params: SetLevelRequestParams) -> EmptyResult:  # pyright: ignore[reportDeprecated]
    """Registered so the logging capability is advertised; the client never sets a level."""
    raise NotImplementedError


server = Server("stdio-echo", on_list_tools=list_tools, on_call_tool=call_tool, on_set_logging_level=set_logging_level)


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
    # Flush this process's coverage data before the clean-exit line below. Without this, the
    # data is only written by coverage's atexit hook during interpreter teardown -- and on a
    # slow Windows runner that can overrun the transport's termination grace, so the kill
    # silently destroys the data file and the 100% gate trips on this module's subprocess-only
    # lines. Saving here puts the write before the line the test synchronizes on: once the
    # parent has seen "clean exit", the data is durably on disk and the escalation is harmless.
    # Nothing measured may execute after the save (it would be unrecordable by construction),
    # hence the excluded lines below. The branch is pragma'd because under coverage the
    # instance always exists, and without coverage nothing is measured anyway.
    cov = getattr(coverage.process_startup, "coverage", None)
    if cov is not None:  # pragma: no branch
        # stop() is load-bearing twice over: it ends tracing, making itself the last
        # recordable line, and it leaves nothing new for coverage's atexit re-save to flush --
        # so a kill landing during interpreter teardown cannot corrupt the file save() wrote
        # (coverage opens it with sqlite journaling off; a torn rewrite would not roll back).
        cov.stop()
        cov.save()  # pragma: lax no cover - untraced: stop() above already ended measurement
    # Reached only when the run loop exits because stdin closed; if the process were terminated
    # the test's stderr capture would not see this line. lax no cover: runs after the coverage
    # save by design, so it can never appear covered.
    print("stdio-echo: clean exit", file=sys.stderr, flush=True)  # pragma: lax no cover


if __name__ == "__main__":
    anyio.run(main)
