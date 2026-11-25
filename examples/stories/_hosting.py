"""Server-side hosting scaffold for story examples.

A story's ``server.py`` / ``server_lowlevel.py`` imports only from here. The
marked lines touch entry-point APIs that a later release reshapes into
free-function entries; isolating them here keeps story bodies stable.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any, TypeAlias

import anyio
import uvicorn
from starlette.applications import Starlette

from mcp.server.lowlevel import Server
from mcp.server.mcpserver import MCPServer
from mcp.server.stdio import stdio_server
from mcp.server.transport_security import TransportSecuritySettings

AnyServer: TypeAlias = "MCPServer | Server[Any]"
ServerFactory = Callable[[], AnyServer]
AppFactory = Callable[[], Starlette]

NO_DNS_REBIND = TransportSecuritySettings(enable_dns_rebinding_protection=False)
"""Harness servers bind 127.0.0.1 and the in-process httpx2 client sends no Origin header."""


def argv_after(flag: str, *, default: str | None = None) -> str:
    """Return the argv token following ``flag``, or ``default`` when the flag is absent."""
    try:
        return sys.argv[sys.argv.index(flag) + 1]
    except ValueError:
        if default is None:
            raise SystemExit(f"missing required {flag}") from None
        return default


def asgi_from(server: AnyServer, *, path: str = "/mcp") -> Starlette:
    """Wrap a server instance in its streamable-HTTP ASGI app for in-process driving."""
    return server.streamable_http_app(  # becomes free fn streamable_http(server, legacy=...)
        streamable_http_path=path,
        stateless_http=False,  # bool folds into a legacy= enum in a later release
        transport_security=NO_DNS_REBIND,
    )


def run_server_from_args(build_server: ServerFactory) -> None:
    """Entry point for ``if __name__ == "__main__"`` in every ``server*.py``.

    Bare argv serves over stdio; ``--http --port N [--path /mcp]`` serves over
    uvicorn on 127.0.0.1:N.
    """
    server = build_server()
    if "--http" in sys.argv:
        port = int(argv_after("--port", default="8000"))
        path = argv_after("--path", default="/mcp")
        anyio.run(_serve_http, server, port, path)
    else:
        anyio.run(_serve_stdio, server)


async def _serve_stdio(server: AnyServer) -> None:
    if isinstance(server, MCPServer):
        await server.run_stdio_async()  # becomes await serve_stdio(server)
    else:
        async with stdio_server() as (read, write):  # becomes await serve_stdio(server)
            await server.run(read, write, server.create_initialization_options())


async def _serve_http(server: AnyServer, port: int, path: str) -> None:
    app = asgi_from(server, path=path)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    await uvicorn.Server(config).serve()


def run_app_from_args(build_app: AppFactory) -> None:
    """Entry point for ``if __name__ == "__main__"`` in app-exporting ``server*.py``.

    App-exporting stories are HTTP-only; ``--port N`` serves the Starlette app over
    uvicorn on 127.0.0.1:N (uvicorn drives the app's own lifespan). No stdio leg.
    """
    port = int(argv_after("--port", default="8000"))
    config = uvicorn.Config(build_app(), host="127.0.0.1", port=port, log_level="error")
    anyio.run(uvicorn.Server(config).serve)
