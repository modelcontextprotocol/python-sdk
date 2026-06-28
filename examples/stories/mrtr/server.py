"""Multi-round tool result (2026 era): a tool returns input_required and resumes from echoed state."""

from mcp_types import (
    BooleanSchema,
    ElicitRequest,
    ElicitRequestedSchema,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
)

from mcp.server.mcpserver import Context, MCPServer
from stories._hosting import run_server_from_args

CONFIRM_SCHEMA = ElicitRequestedSchema(
    properties={"confirm": BooleanSchema(type="boolean", description="Proceed with the deployment?")},
    required=["confirm"],
)


def build_server() -> MCPServer:
    mcp = MCPServer("mrtr-example")

    @mcp.tool(description="Deploy to an environment, asking the user to confirm first.")
    async def deploy(env: str, ctx: Context) -> str | InputRequiredResult:
        responses = ctx.input_responses
        if responses is None or "confirm" not in responses:
            # First round: ask the client to elicit confirmation. request_state is opaque
            # to the client; here it carries the step name so the retry can verify the echo.
            ask = ElicitRequest(
                params=ElicitRequestFormParams(message=f"Deploy to {env}?", requested_schema=CONFIRM_SCHEMA.to_wire())
            )
            return InputRequiredResult(input_requests={"confirm": ask}, request_state="awaiting-confirm")
        # Retry round: the client echoed request_state byte-exact and supplied the answer.
        assert ctx.request_state == "awaiting-confirm", ctx.request_state
        answer = responses["confirm"]
        if isinstance(answer, ElicitResult) and answer.action == "accept" and (answer.content or {}).get("confirm"):
            return f"deployed to {env}"
        return f"deployment to {env} cancelled"

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
