"""Multi-round tool result (2026 era) against the low-level Server."""

from typing import Any

import mcp_types as types

from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.request_state import RequestStateBoundary, RequestStateSecurity
from stories._hosting import run_server_from_args

CONFIRM_SCHEMA: types.ElicitRequestedSchema = {
    "type": "object",
    "properties": {"confirm": {"type": "boolean", "description": "Proceed with the deployment?"}},
    "required": ["confirm"],
}
DEPLOY_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"env": {"type": "string"}},
    "required": ["env"],
}


def build_server() -> Server[Any]:
    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="deploy",
                    description="Deploy to an environment, asking the user to confirm first.",
                    input_schema=DEPLOY_INPUT_SCHEMA,
                )
            ]
        )

    async def call_tool(
        ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult | types.InputRequiredResult:
        assert params.name == "deploy" and params.arguments is not None
        env = params.arguments["env"]
        responses = params.input_responses
        if responses is None or "confirm" not in responses:
            ask = types.ElicitRequest(
                params=types.ElicitRequestFormParams(message=f"Deploy to {env}?", requested_schema=CONFIRM_SCHEMA)
            )
            return types.InputRequiredResult(input_requests={"confirm": ask}, request_state="awaiting-confirm")
        assert params.request_state == "awaiting-confirm", params.request_state
        answer = responses["confirm"]
        if (
            isinstance(answer, types.ElicitResult)
            and answer.action == "accept"
            and (answer.content or {}).get("confirm")
        ):
            return types.CallToolResult(content=[types.TextContent(text=f"deployed to {env}")])
        return types.CallToolResult(content=[types.TextContent(text=f"deployment to {env} cancelled")])

    server = Server("mrtr-example", on_list_tools=list_tools, on_call_tool=call_tool)
    # The lowlevel tier has no construction-time requirement; appending the boundary
    # middleware is the whole opt-in, and it is the identical enforcement MCPServer
    # installs from its request_state_security= parameter.
    server.middleware.append(RequestStateBoundary(RequestStateSecurity.ephemeral()))
    return server


if __name__ == "__main__":
    run_server_from_args(build_server)
