"""SEP-1699: a tool closes its own SSE stream mid-call; the event store buffers the rest. Exports `build_app()`."""

from starlette.applications import Starlette

from mcp.server.mcpserver import Context, MCPServer
from stories._hosting import NO_DNS_REBIND, run_app_from_args
from stories.sse_polling.event_store import InMemoryEventStore


def build_app() -> Starlette:
    mcp = MCPServer("sse-polling-example")

    @mcp.tool()
    async def long_operation(ctx: Context) -> str:
        """Emit progress, close this call's SSE stream, emit more progress, then return.

        Everything sent after `close_sse_stream()` lands in the event store and is
        replayed when the client reconnects with `Last-Event-ID`.
        """
        await ctx.report_progress(0.5, total=1.0, message="before-close")
        await ctx.close_sse_stream()
        await ctx.report_progress(1.0, total=1.0, message="after-close")
        return "resumed"

    # event_store enables Last-Event-ID replay; retry_interval=0 makes the client's
    # reconnect wait a no-op so the example is deterministic without real time.
    return mcp.streamable_http_app(
        event_store=InMemoryEventStore(),
        retry_interval=0,
        transport_security=NO_DNS_REBIND,
    )


if __name__ == "__main__":
    run_app_from_args(build_app)
