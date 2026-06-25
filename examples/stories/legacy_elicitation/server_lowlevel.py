"""Elicitation (handshake-era push style) against the low-level Server."""

from typing import Any

from mcp import types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import run_server_from_args

REGISTRATION_SCHEMA: types.ElicitRequestedSchema = {
    "type": "object",
    "properties": {
        "username": {"type": "string"},
        "plan": {"type": "string", "enum": ["free", "pro", "team"]},
    },
    "required": ["username"],
}
LINK_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"provider": {"type": "string"}},
    "required": ["provider"],
}


def build_server() -> Server[Any]:
    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="register_user", description="Register a new account.", input_schema={"type": "object"}
                ),
                types.Tool(
                    name="link_account", description="Link a third-party account.", input_schema=LINK_INPUT_SCHEMA
                ),
            ]
        )

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        if params.name == "register_user":
            answer = await ctx.session.elicit_form("Please provide your registration details:", REGISTRATION_SCHEMA)
            if answer.action != "accept" or answer.content is None:
                return types.CallToolResult(content=[types.TextContent(text=f"registration {answer.action}")])
            text = f"registered {answer.content['username']} (plan: {answer.content.get('plan') or 'free'})"
            return types.CallToolResult(content=[types.TextContent(text=text)])

        assert params.name == "link_account" and params.arguments is not None
        provider = params.arguments["provider"]
        elicitation_id = f"link-{provider}"
        answer = await ctx.session.elicit_url(
            f"Sign in to {provider} to link your account",
            url=f"https://example.com/oauth/{provider}/authorize",
            elicitation_id=elicitation_id,
        )
        if answer.action != "accept":
            return types.CallToolResult(content=[types.TextContent(text=f"link {answer.action}")])
        await ctx.session.send_elicit_complete(elicitation_id, related_request_id=ctx.request_id)
        return types.CallToolResult(content=[types.TextContent(text=f"linked {provider}")])

    return Server("legacy-elicitation-example", on_list_tools=list_tools, on_call_tool=call_tool)


if __name__ == "__main__":
    run_server_from_args(build_server)
