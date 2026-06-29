"""Progress, in-flight logging, and cancellation from a single long-running tool."""

import anyio
import mcp_types as types

from mcp.server.mcpserver import Context, MCPServer
from stories._hosting import run_server_from_args


def build_server() -> MCPServer:
    mcp = MCPServer("streaming-example")

    @mcp.tool()
    async def countdown(steps: int, ctx: Context) -> dict[str, int]:
        """Emit one progress + one log notification per step; observes cancellation."""
        try:
            for i in range(1, steps + 1):
                await ctx.report_progress(float(i), float(steps), f"step {i}/{steps}")
                # No non-deprecated logging helper on Context yet, so send the raw notification.
                # `related_request_id` keeps it on this request's response stream over streamable HTTP.
                await ctx.request_context.session.send_notification(
                    types.LoggingMessageNotification(
                        params=types.LoggingMessageNotificationParams(
                            level="info", logger="countdown", data=f"step {i}/{steps}"
                        )
                    ),
                    related_request_id=ctx.request_context.request_id,
                )
        except anyio.get_cancelled_exc_class():
            # The client abandoned the call: clean up here, then re-raise — never swallow cancellation.
            raise
        return {"completed": steps, "total": steps}

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
