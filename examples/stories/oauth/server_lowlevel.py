"""OAuth-protected MCP server (lowlevel API): same app shape, hand-built result types."""

from typing import Any

import mcp_types as types
from starlette.applications import Starlette

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import ProviderTokenVerifier
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import NO_DNS_REBIND, run_app_from_args
from stories._shared.auth import InMemoryAuthorizationServerProvider, auth_settings

WHOAMI_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"client_id": {"type": "string"}, "scopes": {"type": "array", "items": {"type": "string"}}},
    "required": ["client_id", "scopes"],
}


def build_app() -> Starlette:
    provider = InMemoryAuthorizationServerProvider()

    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="whoami",
                    description="Return the authenticated principal's client_id and granted scopes.",
                    input_schema={"type": "object"},
                    output_schema=WHOAMI_OUTPUT_SCHEMA,
                ),
            ]
        )

    async def call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        assert params.name == "whoami"
        token = get_access_token()
        assert token is not None
        payload = {"client_id": token.client_id, "scopes": token.scopes}
        return types.CallToolResult(content=[types.TextContent(text=token.client_id)], structured_content=payload)

    server = Server("oauth-example", on_list_tools=list_tools, on_call_tool=call_tool)
    # Unlike MCPServer (auth on the constructor), lowlevel.Server takes auth as streamable_http_app() kwargs.
    return server.streamable_http_app(
        auth=auth_settings(required_scopes=["mcp"]),
        token_verifier=ProviderTokenVerifier(provider),
        auth_server_provider=provider,
        transport_security=NO_DNS_REBIND,
    )


if __name__ == "__main__":
    run_app_from_args(build_app)
