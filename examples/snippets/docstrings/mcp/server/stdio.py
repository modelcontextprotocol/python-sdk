"""Companion examples for src/mcp/server/stdio.py docstrings."""

from __future__ import annotations

from typing import Any

import anyio

from mcp.server.lowlevel.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server


# Stubs for undefined references in examples
async def create_my_server() -> Server[Any]: ...


def module_overview(init_options: InitializationOptions) -> None:
    # region module_overview
    async def run_server():
        async with stdio_server() as (read_stream, write_stream):
            # read_stream contains incoming JSONRPCMessages from stdin
            # write_stream allows sending JSONRPCMessages to stdout
            server = await create_my_server()
            await server.run(read_stream, write_stream, init_options)

    anyio.run(run_server)
    # endregion module_overview
