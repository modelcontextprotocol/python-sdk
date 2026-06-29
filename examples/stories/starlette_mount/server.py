"""Mount an MCPServer in an existing Starlette app at a sub-path, alongside non-MCP routes; exports `build_app()`."""

import contextlib
from collections.abc import AsyncIterator

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from mcp.server.mcpserver import MCPServer
from stories._hosting import NO_DNS_REBIND, run_app_from_args


def build_app() -> Starlette:
    mcp = MCPServer("starlette-mount-example")

    @mcp.tool()
    def greet(name: str) -> str:
        """Return a greeting."""
        return f"Hello, {name}! (served from a Starlette sub-mount)"

    # streamable_http_path="/" puts the MCP endpoint at /api itself, not /api/mcp. Starlette does not run
    # nested lifespans under Mount, so the parent app's lifespan below must enter mcp.session_manager.run().
    mcp_app = mcp.streamable_http_app(streamable_http_path="/", transport_security=NO_DNS_REBIND)

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with mcp.session_manager.run():
            yield

    return Starlette(
        routes=[
            Route("/health", health),
            Mount("/api", app=mcp_app),
        ],
        lifespan=lifespan,
    )


if __name__ == "__main__":
    run_app_from_args(build_app)
