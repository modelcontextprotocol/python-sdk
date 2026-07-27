"""Process-scoped dependency injection via `MCPServer(lifespan=...)`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from stories._hosting import run_server_from_args


@dataclass
class AppState:
    db: dict[str, str]


@asynccontextmanager
async def app_lifespan(server: MCPServer[AppState]) -> AsyncIterator[AppState]:
    """Acquire process-scoped resources at startup; release them at shutdown."""
    db = {"alpha": "one", "beta": "two"}  # e.g. `await pool.connect()`
    try:
        yield AppState(db=db)
    finally:
        db.clear()  # e.g. `await pool.disconnect()`


def build_server() -> MCPServer[AppState]:
    mcp = MCPServer[AppState]("lifespan-example", lifespan=app_lifespan)

    @mcp.tool(description="Look up a key in the process-scoped store.")
    def lookup(key: str, ctx: Context[AppState, Any]) -> str:
        # Interim 3-hop path; shortens to `ctx.state.db` in a later release.
        return ctx.request_context.lifespan_context.db[key]

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
