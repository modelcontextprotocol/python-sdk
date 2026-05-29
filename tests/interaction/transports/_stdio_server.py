"""A real low-level Server over the stdio transport, for the suite's one subprocess test.

Runnable as `python -m tests.interaction.transports._stdio_server` from the repo root; the test
launches it that way via `stdio_client`. Kept separate from the test module so the server lives in
its own importable file (subprocess coverage applies) while the test file follows the suite's
test-only-functions convention.
"""

import sys
from typing import Any

import anyio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import LoggingLevel, TextContent, Tool

server = Server("stdio-echo")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="echo",
            inputSchema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    assert name == "echo"
    text = arguments["text"]
    await server.request_context.session.send_log_message(level="info", data=f"echoing {text}", logger="echo")
    return [TextContent(type="text", text=text)]


@server.set_logging_level()
async def set_logging_level(level: LoggingLevel) -> None:
    """Registered so the logging capability is advertised; the client never sets a level."""
    raise NotImplementedError


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
    # Reached only when the run loop exits because stdin closed; if the process were terminated
    # the test's stderr capture would not see this line.
    print("stdio-echo: clean exit", file=sys.stderr, flush=True)


if __name__ == "__main__":
    anyio.run(main)
