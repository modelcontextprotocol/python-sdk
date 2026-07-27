"""Serve over Streamable HTTP with JSON responses (no SSE stream); HTTP-only, so this exports ``build_app()``.

The 2026-07-28 path is stateless and JSON-only by construction today; the
``json_response=True`` flag also forces JSON for the legacy (2025-era) branch on
the same endpoint. Mid-call notifications are dropped.
"""

from starlette.applications import Starlette

from mcp.server.mcpserver import Context, MCPServer
from stories._hosting import NO_DNS_REBIND, run_app_from_args


def build_app() -> Starlette:
    mcp = MCPServer("json-response-example")

    @mcp.tool()
    async def greet(name: str, ctx: Context) -> str:
        """Report progress mid-call, then return a greeting."""
        await ctx.report_progress(0.5, total=1.0, message="halfway")
        return f"Hello, {name}!"

    return mcp.streamable_http_app(json_response=True, transport_security=NO_DNS_REBIND)


if __name__ == "__main__":
    run_app_from_args(build_app)
