"""Dispatch-layer middleware: one function wraps every inbound MCP message."""

from typing import Any

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import MCPServer
from stories._hosting import run_server_from_args


def build_server() -> MCPServer:
    mcp = MCPServer("middleware-example")
    log: list[str] = []

    async def record_calls(ctx: ServerRequestContext[Any], call_next: CallNext) -> HandlerResult:
        log.append(ctx.method)
        try:
            return await call_next(ctx)
        finally:
            log.append(f"{ctx.method}:done")

    # MCPServer exposes no public middleware hook yet; the list lives on the wrapped
    # lowlevel Server. DO NOT copy this private reach — see server_lowlevel.py for the
    # public `server.middleware.append(...)` registration.
    mcp._lowlevel_server.middleware.append(record_calls)  # pyright: ignore[reportPrivateUsage]

    @mcp.tool()
    def audit_log() -> list[str]:
        """Return every method the middleware has observed so far."""
        return list(log)

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
