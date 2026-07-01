"""Transport entry point for the "todos" reference server (the application itself lives in todos.py).

stdio by default (a host spawns it as a child process), Streamable HTTP behind
`--transport streamable-http`. Both transports negotiate the protocol revision per
connection: a 2025-era client and a 2026-era client can talk to the same process.
"""

import os
import sys

import anyio
import click

from .todos import mcp, serve_stdio


@click.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio", "streamable-http"]),
    default="stdio",
    help="Transport to serve on",
)
@click.option("--port", type=int, default=None, help="HTTP port (default: $PORT or 3000)")
def main(transport: str, port: int | None) -> int:
    if transport == "stdio":
        print("[todos] serving over stdio", file=sys.stderr)
        anyio.run(serve_stdio)
    else:
        resolved_port = port if port is not None else int(os.environ.get("PORT", "3000"))
        print(f"[todos] listening on http://127.0.0.1:{resolved_port}/mcp", file=sys.stderr)
        mcp.run(transport="streamable-http", port=resolved_port)
    return 0
