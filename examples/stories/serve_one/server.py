"""Kernel drivers: drive an `MCPServer` via `serve_loop` directly.

The drivers (`serve_loop` / `serve_one`) take a `lowlevel.Server`; `MCPServer`
has no public accessor for its underlying one yet, so this file reaches
`_lowlevel_server`. See `server_lowlevel.py` for the clean shape.
"""

import anyio

from mcp.server.mcpserver import MCPServer
from mcp.server.runner import serve_loop  # deep-path import; shorter re-export planned
from mcp.server.stdio import stdio_server


def build_server() -> MCPServer:
    mcp = MCPServer("serve-one-example")

    @mcp.tool()
    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    return mcp


async def main() -> None:
    mcp = build_server()
    server = mcp._lowlevel_server  # pyright: ignore[reportPrivateUsage]  # no public accessor yet
    async with server.lifespan(server) as lifespan_state:
        async with stdio_server() as (read_stream, write_stream):
            await serve_loop(server, read_stream, write_stream, lifespan_state=lifespan_state)


if __name__ == "__main__":
    anyio.run(main)
