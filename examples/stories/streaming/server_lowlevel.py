"""Progress, in-flight logging, and cancellation against the low-level Server."""

from typing import Any

import anyio
import mcp_types as types

from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import run_server_from_args

COUNTDOWN_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"steps": {"type": "integer"}},
    "required": ["steps"],
}


def build_server() -> Server[Any]:
    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="countdown",
                    description="Emit one progress + one log notification per step; observes cancellation.",
                    input_schema=COUNTDOWN_INPUT_SCHEMA,
                )
            ]
        )

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.name == "countdown" and params.arguments is not None
        steps = int(params.arguments["steps"])
        try:
            for i in range(1, steps + 1):
                await ctx.session.report_progress(float(i), float(steps), f"step {i}/{steps}")
                await ctx.session.send_notification(
                    types.LoggingMessageNotification(
                        params=types.LoggingMessageNotificationParams(
                            level="info", logger="countdown", data=f"step {i}/{steps}"
                        )
                    ),
                    related_request_id=ctx.request_id,
                )
        except anyio.get_cancelled_exc_class():
            raise
        return types.CallToolResult(
            content=[types.TextContent(text=f"completed {steps}/{steps}")],
            structured_content={"completed": steps, "total": steps},
        )

    async def set_logging_level(
        ctx: ServerRequestContext[Any], params: types.SetLevelRequestParams
    ) -> types.EmptyResult:
        """Registered so the server advertises the `logging` capability; never called."""
        raise NotImplementedError

    return Server(
        "streaming-example",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_set_logging_level=set_logging_level,
    )


if __name__ == "__main__":
    run_server_from_args(build_server)
